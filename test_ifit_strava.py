import datetime
import dateutil.parser
import pytest
from unittest.mock import MagicMock

import ifit_strava


def test_is_similar_activity():
    workout_1 = MagicMock(started_at='2020-06-01T06:36:58.517Z', duration=2613)
    activity_1 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:36:58.517Z'),
                           elapsed_time=datetime.timedelta(seconds=2613))
    assert ifit_strava.is_similar_activity(workout_1, activity_1)

    # starts 6 mins (ish) earlier
    activity_2 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:30:22.293Z'),
                           elapsed_time=datetime.timedelta(seconds=2613))
    assert ifit_strava.is_similar_activity(workout_1, activity_2)

    # starts 11 mins (ish) earlier
    activity_3 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:48:03.384Z'),
                           elapsed_time=datetime.timedelta(seconds=2613))
    assert not ifit_strava.is_similar_activity(workout_1, activity_3)

    # starts 2 mins (ish) later and is 5 seconds longer
    activity_4 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:38:27.930Z'),
                           elapsed_time=datetime.timedelta(seconds=2618))
    assert ifit_strava.is_similar_activity(workout_1, activity_4)

    # starts 3 mins (ish) earlier and is 75 seconds longer
    activity_5 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:33:37.535Z'),
                           elapsed_time=datetime.timedelta(seconds=2688))
    assert not ifit_strava.is_similar_activity(workout_1, activity_5)

    # different day
    workout_2 = MagicMock(started_at='2020-06-02T06:36:58.517Z', duration=2613)
    assert not ifit_strava.is_similar_activity(workout_2, activity_1)


def test_find_similar_activities():
    workout_1 = MagicMock(started_at='2020-06-01T06:36:58.517Z', duration=2613)

    # only one similar
    activity_1 = MagicMock(start_date=dateutil.parser.parse('2020-05-30T17:28:38.329Z'),
                           elapsed_time=datetime.timedelta(seconds=2203))
    activity_2 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:30:22.293Z'),
                           elapsed_time=datetime.timedelta(seconds=2613))
    activity_3 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:36:58.517Z'),
                           elapsed_time=datetime.timedelta(seconds=2613))
    activity_4 = MagicMock(start_date=dateutil.parser.parse('2020-06-03T08:01:22.930Z'),
                           elapsed_time=datetime.timedelta(seconds=3094))

    with pytest.raises(AssertionError):
        # not in ascending order of time
        ifit_strava.find_similar_activities(workout_1, [activity_2, activity_1])

    assert ifit_strava.find_similar_activities(workout_1, [activity_1, activity_3, activity_4]) == [activity_3]
    assert ifit_strava.find_similar_activities(workout_1, [activity_3, activity_4]) == [activity_3]
    assert ifit_strava.find_similar_activities(workout_1, [activity_1, activity_3]) == [activity_3]

    assert ifit_strava.find_similar_activities(
        workout_1, [activity_1, activity_2, activity_3, activity_4]) == [activity_2, activity_3]

    # Test edge case where Strava (or stravalib) doesn't have millisecond
    # accuracy, so activities might sort slightly to the left or right of where
    # they should be

    # Same as activity_3 to the nearest second
    activity_5 = MagicMock(start_date=dateutil.parser.parse('2020-06-01T06:36:58Z'),
                           elapsed_time=datetime.timedelta(seconds=2613))
    assert ifit_strava.find_similar_activities(workout_1, [activity_1, activity_5, activity_4]) == [activity_5]

    # Test similar edge case where activity sorts off the end of the array
    # (it's really already the last element in the array, but the milliseconds
    # are different).
    assert ifit_strava.find_similar_activities(workout_1, [activity_1, activity_5]) == [activity_5]
