#!/usr/bin/env python3

import bisect
import click
import collections
import dateutil.parser
from flask import Flask, request
import glob
import http.cookiejar
import logging
import os
import re
import requests
import stravalib
import sys
import tcxparser
import threading
import time
import yaml

_AUTH_TIMEOUT = 60
_MAX_PAGES = 10
_MIN_WORKOUT_SIZE = 1024
_SCOPE = ['activity:read', 'activity:write']
_WORKOUT_LINK_RE = re.compile(r'href="/workout/\w+/(\w+)"')
_WORKOUT_TCX_URL = "https://www.ifit.com/workout/export/tcx/"
_WORKOUTS_URL = "https://www.ifit.com/me/workouts"

Workout = collections.namedtuple('Workout', 'workout_id started_at duration notes tcx_file')


def _get_workouts(url, cj):
    r = requests.get(url, cookies=cj)
    workouts = _WORKOUT_LINK_RE.findall(r.text)
    return workouts


def _check_workout(data):
    if not data.startswith("<?xml "):
        logging.error("Workout doesn't look like an XML document")
        return False
    if data.find("<TrainingCenterDatabase") == -1 or data.find("</TrainingCenterDatabase>") == -1:
        logging.error("Workout doesn't look like a complete TCX document")
        return False
    return True


def _check_workout_file(filename):
    with open(filename, 'r') as f:
        return _check_workout(f.read())


def _download_workout(workout_id, path, cj):
    filename = os.path.join(path, workout_id)
    if os.path.exists(filename) and _check_workout_file(filename):
        logging.debug(f"Workout {workout_id} already downloaded at {filename} and looks ok")
    else:
        url = _WORKOUT_TCX_URL + workout_id
        logging.info(f"Saving workout {workout_id} to {filename}")
        r = requests.get(url, cookies=cj)
        with open(filename, 'w') as f:
            f.write(r.text)


def _load_config(config_file):
    with open(config_file, 'r') as f:
        cfg = yaml.load(f, Loader=yaml.FullLoader)
    return cfg


def _write_config(config_file, data):
    with open(config_file, 'w') as f:
        yaml.dump(data, f)


def _authorise(client, client_id, client_secret, redirect_uri, auth_port):
    authorisation_url = client.authorization_url(client_id=client_id, scope=_SCOPE, redirect_uri=redirect_uri)
    logging.info(f"Authorisation url: {authorisation_url}")

    def create_app():
        app = Flask(__name__)
        app.config['strava_token_response'] = None
        return app

    def shutdown_server():
        logging.info("Shutting down flask server")
        func = request.environ.get('werkzeug.server.shutdown')
        if func is None:
            raise RuntimeError('Not running with the Werkzeug Server')
        func()

    app = create_app()

    @app.route('/authorised')
    def strava_authorised():
        logging.debug(f"Request args: {dict(request.args.items())}")
        error = request.args.get('error')
        if error is not None:
            raise RuntimeError(f"Received error callback from Strava: {error}")
        code = request.args.get('code')
        scope = request.args.get('scope')

        if not all(s in scope for s in _SCOPE):
            raise RuntimeError(f"Didn't get all expected permissions ({_SCOPE}) in scope response ({scope})")

        response = client.exchange_code_for_token(client_id=client_id, client_secret=client_secret, code=code)
        logging.debug(f"exchange_code_for_token response: {response}")

        app.config['strava_token_response'] = response

        shutdown_server()
        return 'OK'

    flask_thread = threading.Thread(target=app.run, kwargs={'debug': False, 'port': auth_port})
    flask_thread.start()

    # wait for the authorisation url to be clicked
    flask_thread.join(timeout=_AUTH_TIMEOUT)
    if flask_thread.is_alive():
        raise RuntimeError(f"Authorisation url not clicked after {_AUTH_TIMEOUT}s")

    return app.config['strava_token_response']


def _strava_upload(workout, strava, gear_id=None):
    logging.info(f"Uploading {workout}")
    # TODO: rate limiting
    upload = strava.upload_activity(activity_file=open(workout.tcx_file, 'r'),
                                    name=workout.notes,
                                    description="iFit virtual treadmill run",
                                    activity_type='VirtualRun',
                                    data_type='tcx')
    activity = upload.wait()
    url = f"https://www.strava.com/activities/{activity.id}"
    logging.info(f"Uploaded to {url}")
    if gear_id is not None:
        logging.debug(f"Updating activity with gear_id {gear_id}")
        strava.update_activity(activity.id, gear_id=gear_id)


def _get_ifit_workouts(workout_dir):
    workouts = []
    for workout_file in glob.glob(os.path.join(workout_dir, '*')):
        tcx = tcxparser.TCXParser(workout_file)
        workout = Workout(workout_id=os.path.basename(workout_file),
                          started_at=tcx.started_at,
                          duration=tcx.duration,
                          notes=tcx.activity_notes,
                          tcx_file=workout_file)
        logging.debug(f"Workout: {workout}")
        workouts.append(workout)
    workouts.sort(key=lambda x: x.started_at)
    return workouts


def _get_start_time_delta(workout, strava_activity):
    workout_start_time = dateutil.parser.parse(workout.started_at)
    return abs((strava_activity.start_date - workout_start_time).total_seconds())


def is_similar_activity(workout, strava_activity):
    # started within 10 mins of each other and duration is no more than 30s different
    start_time_delta = _get_start_time_delta(workout, strava_activity)
    duration_delta = abs(workout.duration - strava_activity.elapsed_time.total_seconds())
    return start_time_delta < 10 * 60 and duration_delta < 30


def _log_debug_slice(workout, strava_activities, start_times, index, size):
    start_index = index - size
    end_index = index + 1 + size
    if start_index < 0:
        start_index = 0
    if end_index > len(strava_activities):
        end_index = len(strava_activities)
    for i in range(start_index, end_index):
        marker = '<<<' if i < index else '>>>' if i > index else '==='
        logging.debug(f"{marker} {i}: {strava_activities[i]} {start_times[i]}")


def _search_near(workout, strava_activities, start_times, index):
    '''Search for similar activities to workout from a given index in the list of activities.

    index should be just to the left of the workout if it's in the list,
    however since we're searching by time and the precision differs between
    iFit and Strava (iFit has millisecond-level, Strava (or stravalib)
    truncates to seconds), it's possible that the iFit workout time inserts
    just after the time of the existing Strava representation of the same
    workout. Hence we always search at least one to the left and right.

    '''
    similar_activities = []

    # index could be off either end of the array if that's where the workout's
    # time would sort to, so adjust it back
    if index < 0:
        index = 0
    if index >= len(strava_activities):
        index = len(strava_activities) - 1

    left_index = index
    right_index = index + 1

    time_cutoff = 24 * 60 * 60
    min_search_distance = 1

    continue_left = True
    continue_right = True
    distance = 0

    def _search(ii, left):
        marker = 'left' if left else 'right'
        logging.debug(f"Searching {marker} {ii} {start_times[ii]} {strava_activities[ii]}")
        if is_similar_activity(workout, strava_activities[ii]):
            logging.debug(f"Found similar activity going {marker} at {ii} {strava_activities[ii]}")
            if left:
                similar_activities.insert(0, strava_activities[ii])
            else:
                similar_activities.append(strava_activities[ii])

    def _should_continue(ii, left):
        if left:
            return ii >= 0 and (distance < min_search_distance
                                or _get_start_time_delta(workout, strava_activities[ii]) < time_cutoff)
        else:
            return ii < len(strava_activities) and (distance < min_search_distance or
                                                    _get_start_time_delta(workout, strava_activities[ii]) < time_cutoff)

    while continue_left or continue_right:
        continue_left = _should_continue(left_index, left=True)
        if continue_left:
            _search(left_index, left=True)
            left_index -= 1
        continue_right = _should_continue(right_index, left=False)
        if continue_right:
            _search(right_index, left=False)
            right_index += 1
        distance += 1

    return similar_activities


def find_similar_activities(workout, strava_activities):
    '''Find similar Strava activities to the given workout

    TODO: this is over-complicated, something simpler would likely work fine!

    This works by searching where the workout should be based on its start time
    in the list of Strava activities (which is sorted by start time). Since
    times can be off and sometimes there are some 'false starts' etc., it then
    searches outwards from that index doing a fuzzy match based on start time
    and duration (see is_similar_activity).
    '''
    assert len(strava_activities) > 0

    start_times = [a.start_date for a in strava_activities]
    assert start_times == sorted(start_times)
    workout_start_time = dateutil.parser.parse(workout.started_at)
    index = bisect.bisect_left(start_times, workout_start_time)

    logging.debug(
        f"Searching for similar activities to {workout} at index {index} in {len(strava_activities)} activities")
    _log_debug_slice(workout, strava_activities, start_times, index, 2)

    return _search_near(workout, strava_activities, start_times, index)


def _should_skip(workout, skip):
    if workout.duration < 3 * 60:
        logging.debug(f"Skipping workout {workout} due to short duration")
        return True
    if workout.workout_id in skip:
        logging.debug(f"Skipping workout {workout} due to being on skip list")
        return True
    return False


@click.group(chain=True)
@click.option('-c', '--config-file', default='config/config.yaml', help='Config file')
@click.option('-t', '--token-file', default='config/token.yaml', help='Token file path (generated file)')
@click.option('-v', '--verbose/--no-verbose', default=False, help='Enable verbose logging')
@click.option('-w', '--workout-dir', default='workouts', help='Directory to save cached iFit workouts in')
@click.pass_context
def ifit_strava(ctx, config_file, token_file, verbose, workout_dir):
    ctx.ensure_object(dict)

    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    logging.getLogger('stravalib').setLevel(logging.INFO if verbose else logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.INFO)

    ctx.obj['config_file'] = config_file
    ctx.obj['token_file'] = token_file
    ctx.obj['workout_dir'] = workout_dir


@ifit_strava.command(help='Download workouts from ifit.com')
@click.option('--cookies-file',
              default='config/cookies.txt',
              help='Mozilla format cookies.txt file containing ifit.com session cookies')
@click.pass_context
def download(ctx, cookies_file):
    workout_dir = ctx.obj['workout_dir']

    cj = http.cookiejar.MozillaCookieJar()
    cj.load(cookies_file)

    workouts = list()
    for i in range(1, _MAX_PAGES):
        workouts.extend(_get_workouts(_WORKOUTS_URL + f"?page={i}", cj))

    logging.debug(f"Found {len(workouts)} workouts")

    if len(workouts) == 0:
        raise RuntimeError("Found 0 workouts, perhaps your cookies have expired?")

    if not os.path.exists(workout_dir):
        os.makedirs(workout_dir)

    for workout_id in workouts:
        _download_workout(workout_id, workout_dir, cj)


@ifit_strava.command(help='Authenticate with strava')
@click.pass_context
def auth(ctx):
    config = _load_config(ctx.obj['config_file'])

    client_id = config['strava']['client_id']
    client_secret = config['strava']['client_secret']

    client = stravalib.Client()

    if os.path.exists(ctx.obj['token_file']):
        token_config = _load_config(ctx.obj['token_file'])
    else:
        token_config = {
            'refresh_token': None,
            'access_token': None,
            'expires_at': None,
        }

    if token_config['refresh_token'] is None:
        # need to authorise
        token_response = _authorise(client, client_id, client_secret, config['strava']['redirect_uri'],
                                    config['strava']['auth_port'])
        logging.info(f"authorise response: {token_response}")

        token_config['access_token'] = token_response['access_token']
        token_config['refresh_token'] = token_response['refresh_token']
        token_config['expires_at'] = token_response['expires_at']

    if token_config['access_token'] is None or token_config['expires_at'] is None or time.time(
    ) > token_config['expires_at']:
        # need a new access token
        refresh_response = client.refresh_access_token(client_id=client_id,
                                                       client_secret=client_secret,
                                                       refresh_token=token_config['refresh_token'])
        logging.info(f"Refresh response: {refresh_response}")

        token_config['access_token'] = refresh_response['access_token']
        token_config['refresh_token'] = refresh_response['refresh_token']
        token_config['expires_at'] = refresh_response['expires_at']

    logging.debug(f"Saving token config to {ctx.obj['token_file']}")
    _write_config(ctx.obj['token_file'], token_config)


@ifit_strava.command(help='Idempotently upload workouts to Strava')
@click.pass_context
def upload(ctx):
    config = _load_config(ctx.obj['config_file'])
    token_config = _load_config(ctx.obj['token_file'])
    workout_dir = ctx.obj['workout_dir']

    if token_config['access_token'] is None or token_config['expires_at'] is None or time.time(
    ) > token_config['expires_at']:
        logging.error("Access token missing or expired")
        sys.exit(1)

    strava = stravalib.Client()
    strava.access_token = token_config['access_token']
    logging.debug(f"Using strava access token {strava.access_token}")

    athlete = strava.get_athlete()
    logging.debug(f"Strava athlete id {athlete.id}")

    ifit_workouts = _get_ifit_workouts(workout_dir)
    earliest_workout_start = ifit_workouts[0].started_at
    logging.debug(f"Earliest iFit workout started at {earliest_workout_start}")

    strava_activities = list(strava.get_activities(after=earliest_workout_start))

    for workout in ifit_workouts:
        if _should_skip(workout, config['skip']):
            continue

        similar_activities = find_similar_activities(workout, strava_activities)

        if len(similar_activities) != 0:
            logging.debug(f"Skipping workout {workout} due to similar activities {similar_activities}")
        else:
            _strava_upload(workout, strava)


if __name__ == '__main__':
    ifit_strava()
