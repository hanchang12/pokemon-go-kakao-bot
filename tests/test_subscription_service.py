from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.subscription_service import (
    next_fire_from,
    parse_time_of_day,
)


KST = ZoneInfo("Asia/Seoul")


def test_parse_time_of_day_accepts_valid_times():
    assert parse_time_of_day("09:00") == time(9, 0)
    assert parse_time_of_day("23:59") == time(23, 59)
    assert parse_time_of_day("0:00") == time(0, 0)


def test_parse_time_of_day_rejects_invalid_times():
    assert parse_time_of_day("24:00") is None
    assert parse_time_of_day("12:60") is None
    assert parse_time_of_day("not a time") is None


def test_next_fire_from_uses_today_when_time_not_yet_passed():
    now = datetime(2026, 9, 14, 8, 0, tzinfo=KST)

    result = next_fire_from(time(9, 0), now)

    assert result == datetime(2026, 9, 14, 9, 0, tzinfo=KST)


def test_next_fire_from_rolls_to_tomorrow_when_time_already_passed():
    now = datetime(2026, 9, 14, 10, 0, tzinfo=KST)

    result = next_fire_from(time(9, 0), now)

    assert result == datetime(2026, 9, 15, 9, 0, tzinfo=KST)
