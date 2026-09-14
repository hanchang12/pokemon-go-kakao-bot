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
    now = datetime(2026, 9, 14, 8, 0, tzinfo=KST)  # 2026-09-14 is a Monday

    result = next_fire_from("digest", time(9, 0), now)

    assert result == datetime(2026, 9, 14, 9, 0, tzinfo=KST)


def test_next_fire_from_rolls_to_tomorrow_when_time_already_passed():
    now = datetime(2026, 9, 14, 10, 0, tzinfo=KST)

    result = next_fire_from("digest", time(9, 0), now)

    assert result == datetime(2026, 9, 15, 9, 0, tzinfo=KST)


def test_next_fire_from_raid_hour_rolls_to_next_wednesday():
    now = datetime(2026, 9, 14, 8, 0, tzinfo=KST)  # Monday

    result = next_fire_from("raid_hour", time(17, 50), now)

    assert result == datetime(2026, 9, 16, 17, 50, tzinfo=KST)  # Wednesday


def test_next_fire_from_raid_hour_rolls_to_following_week_when_past():
    now = datetime(2026, 9, 16, 19, 0, tzinfo=KST)  # Wednesday, after 17:50

    result = next_fire_from("raid_hour", time(17, 50), now)

    assert result == datetime(2026, 9, 23, 17, 50, tzinfo=KST)


def test_next_fire_from_spotlight_hour_rolls_to_next_thursday():
    now = datetime(2026, 9, 14, 8, 0, tzinfo=KST)  # Monday

    result = next_fire_from("spotlight_hour", time(18, 0), now)

    assert result == datetime(2026, 9, 17, 18, 0, tzinfo=KST)  # Thursday
