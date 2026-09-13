from datetime import datetime
from zoneinfo import ZoneInfo

from app.scheduler import next_collection_at


KST = ZoneInfo("Asia/Seoul")


def test_next_collection_is_same_day_at_6am():
    now = datetime(2026, 9, 13, 5, 30, tzinfo=KST)
    assert next_collection_at(now) == datetime(2026, 9, 13, 6, 0, tzinfo=KST)


def test_next_collection_is_same_day_at_noon():
    now = datetime(2026, 9, 13, 6, 0, tzinfo=KST)
    assert next_collection_at(now) == datetime(2026, 9, 13, 12, 0, tzinfo=KST)


def test_next_collection_is_same_day_at_6pm():
    now = datetime(2026, 9, 13, 12, 0, tzinfo=KST)
    assert next_collection_at(now) == datetime(2026, 9, 13, 18, 0, tzinfo=KST)


def test_next_collection_rolls_to_next_day():
    now = datetime(2026, 9, 13, 18, 0, tzinfo=KST)
    assert next_collection_at(now) == datetime(2026, 9, 14, 6, 0, tzinfo=KST)
