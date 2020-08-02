# ifit-strava [![graham33](https://circleci.com/gh/graham33/ifit-strava.svg?style=svg)](https://app.circleci.com/pipelines/github/graham33/ifit-strava)
Downloads [iFit] workouts and uploads them to [Strava].

## Installation
You can install ifit-strava like any other python script, e.g. using `pip`
directly, [Nixpkgs] (see the provided [shell.nix](./shell.nix)), or conda.

The primary dependency is [stravalib] and currently a patched version is
required to support the 'Virtual Run' activity type (see [stravalib PR#199]). If
you don't want to bother building that you could change the activity type to
just a plain run (see the `_strava_upload` function). [tcxparser] is also
needed.

## Configuration
ifit-strava takes a YAML config file, by default `config/config.yaml`. See
([example_config/config.yaml](./example_config/config.yaml) for an example. The
configuration options are explained below:

* `strava`
  * `auth_port` and `redirect_uri`: the port to run the authorisation webserver
    on and the URL on which it is exposed externally (see Authentication below)
  * `client_id` and `client_secret`: Strava authorisation credentials
  * `gear_id`: The ID of the 'gear' (i.e. shoes) you want the uploaded
    activities to be marked as using. Optional.
* `skip`: Optional list of bad/unwanted iFit workout IDs to skip uploading

**Note**: authentication with iFit currently works in a hacky way by using a
saved `cookies.txt` file. Unfortunately this will need to be kept up to date
(although the cookies last about a month before expiry). The intention is to
improve this at some point. See the Authentication section for details.

To obtain the gear ID, I just inspect the HTML on the gear section of your
Strava profile. There is likely a better way.

## Usage
There are three main commands that `ifit_strava.py` exposes:

* **download**: downloads workouts from iFit
* **auth**: authenticates with Strava
* **upload**: uploads downloaded workouts to Strava

You can run these all together or a subset, e.g.:

```bash
./ifit_strava.py download auth upload
```

ifit-strava is designed to be idempotent, so you can run it multiple times and
if nothing has changed it will do nothing. I personally run the above command on
a cron every 15 minutes, so any workouts I do are automatically uploaded within
15 mins.

Use `-v` for verbose logging and `--help` to see other options.

## Authentication

### iFit
As explained above, authentication with iFit currently works in a hacky way by
using a saved `cookies.txt` file.

The easiest way to get one is to log in to the iFit website in a browser and
save it, e.g. using the [cookies.txt extension] for Chrome, to
`config/cookies.txt` (use the `--cookies-file` option to the `download` command
to specify a different file).

Unfortunately this will need to be kept up to date manually (although the
cookies last about a month before expiry). The intention is to improve this at
some point, e.g. by using a proper iFit API with a username/password, if one
exists. Suggestions welcome!

### Strava
Strava authentication is a little complicated and is explained more fully in the
Strava docs and by [stravalib]. Firstly, one must register an application to
obtain credentials (you should register your own application). To actually use
the API, one needs to obtain an access token from the client credentials for a
given scope of (e.g. read/write activity). This access token must then be
periodically renewed.

In order to validate the client and confirm the user wants the application to
access the given scope, Strava 'calls back' on a URI which is configured for the
application. **This means you need to run an externally visible webserver** for
initial authentication. Once you have an access token it can be saved and
renewed, so you only need this the first time.

ifit-strava contains a simple implementation of this using Flask. You should run
it (at least until you obtain an access token) on a host with an externally
visible IP (or perhaps port-forward/reverse-proxy to it) and configure the port
the server should run on and the corresponding external URL in the config
(described above). Then, when you run the `auth` command for the first time,
ifit-strava will obtain and log an authorisation URL from stravalib which you
should paste into your browser. When you visit this URL (on strava.com) it will
ask you to confirm the application's access to the required scope, and then call
you back on the URL provided with a (short-lived) access token, an expiry time
and a refresh token that can be used to get a new access token. ifit-strava
saves these tokens in `config/token.yaml` and will automatically refresh your
access token when next invoked if it has expired. You should keep these tokens
safe (as you should your client credentials) so **be careful checkng these into
git**. I use [git-crypt] to make this easy.

## Issues/TODO
* Find a way to obtain iFit credentials from username/password via a proper API
* Find a better way to obtain the list of workouts, rather than parsing HTML
* Strava interactions occasionally fail with an auth error - possibly because
  the token expires during operations (should probably renew if the token has
  almost expired).
* Some hardcoded values should probably be exposed as options
* Better way to obtain gear ID
* Get [stravalib PR#199] merged
* Upstream tcxparser Nix expression

[cookies.txt extension]: https://chrome.google.com/webstore/detail/cookiestxt/njabckikapfpffapmjgojcnbfjonfjfg
[git-crypt]: https://github.com/AGWA/git-crypt
[iFit]: https://www.ifit.com
[Nixpkgs]: https://github.com/NixOS/nixpkgs
[Strava]: https://www.strava.com
[Strava docs]: http://developers.strava.com
[stravalib]: https://github.com/hozn/stravalib
[stravalib PR#199]: https://github.com/hozn/stravalib/pull/199
[tcxparser]: https://pypi.org/project/python-tcxparser/
