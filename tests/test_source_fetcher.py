from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app import source_fetcher


KST = ZoneInfo("Asia/Seoul")
HTML = """
<span class="event-header-item-wrapper" data-event-type="raid-hour"
 data-event-occurrence-id="raid-1" data-event-local-time="true"
 data-event-start-date="2026-09-16T18:00:00">
 <a href="/events/raid-1/"><h2>Test Raid Hour</h2></a>
</span>
<span class="event-header-item-wrapper" data-event-type="raid-hour"
 data-event-occurrence-id="raid-1" data-event-local-time="true"
 data-event-end-date="2026-09-16T19:00:00">
 <a href="/events/raid-1/"><h2>Test Raid Hour</h2></a>
</span>
"""


def test_fetch_event_candidates_merges_start_and_end(monkeypatch):
    response = SimpleNamespace(text=HTML, raise_for_status=lambda: None)
    monkeypatch.setattr(source_fetcher.httpx, "get", lambda *args, **kwargs: response)

    result = source_fetcher.fetch_event_candidates(
        datetime(2026, 9, 13, tzinfo=KST),
        datetime(2026, 10, 13, tzinfo=KST),
    )

    assert "type: raid-hour" in result
    assert "title: Test Raid Hour" in result
    assert "start_at: 2026-09-16T18:00:00+09:00" in result
    assert "end_at: 2026-09-16T19:00:00+09:00" in result
    assert "https://leekduck.com/events/raid-1/" in result


ONGOING_HTML = """
<span class="event-header-item-wrapper" data-event-type="event"
 data-event-occurrence-id="2026-09-08-mega-squads" data-event-local-time="true"
 data-event-end-date="2026-09-14T20:00:00"
 data-event-start-date-check="2026-09-08T10:00:00">
 <a href="/events/mega-squads/"><h2>Mega Squads</h2></a>
</span>
"""


def test_in_progress_event_uses_start_date_check(monkeypatch):
    """Leek Duck omits data-event-start-date for events already under way and
    only exposes the real start via data-event-start-date-check. Without the
    fallback every currently-running event is dropped, so '포고봇 오늘' and
    '포고봇 지금 뭐해' always come back empty."""
    response = SimpleNamespace(text=ONGOING_HTML, raise_for_status=lambda: None)
    monkeypatch.setattr(source_fetcher.httpx, "get", lambda *args, **kwargs: response)

    result = source_fetcher.fetch_event_candidates(
        datetime(2026, 9, 13, 23, 0, tzinfo=KST),
        datetime(2026, 10, 13, tzinfo=KST),
    )

    assert "title: Mega Squads" in result
    assert "start_at: 2026-09-08T10:00:00+09:00" in result
    assert "end_at: 2026-09-14T20:00:00+09:00" in result


def test_explicit_start_date_wins_over_check(monkeypatch):
    html = ONGOING_HTML.replace(
        'data-event-start-date-check="2026-09-08T10:00:00"',
        'data-event-start-date="2026-09-09T10:00:00"'
        ' data-event-start-date-check="2026-09-08T10:00:00"',
    )
    response = SimpleNamespace(text=html, raise_for_status=lambda: None)
    monkeypatch.setattr(source_fetcher.httpx, "get", lambda *args, **kwargs: response)

    result = source_fetcher.fetch_event_candidates(
        datetime(2026, 9, 13, 23, 0, tzinfo=KST),
        datetime(2026, 10, 13, tzinfo=KST),
    )

    assert "start_at: 2026-09-09T10:00:00+09:00" in result
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app import source_fetcher


KST = ZoneInfo("Asia/Seoul")
HTML = """
<span class="event-header-item-wrapper" data-event-type="raid-hour"
 data-event-occurrence-id="raid-1" data-event-local-time="true"
 data-event-start-date="2026-09-16T18:00:00">
 <a href="/events/raid-1/"><h2>Test Raid Hour</h2></a>
</span>
<span class="event-header-item-wrapper" data-event-type="raid-hour"
 data-event-occurrence-id="raid-1" data-event-local-time="true"
 data-event-end-date="2026-09-16T19:00:00">
 <a href="/events/raid-1/"><h2>Test Raid Hour</h2></a>
</span>
"""


def test_fetch_event_candidates_merges_start_and_end(monkeypatch):
    response = SimpleNamespace(text=HTML, raise_for_status=lambda: None)
    monkeypatch.setattr(source_fetcher.httpx, "get", lambda *args, **kwargs: response)

    result = source_fetcher.fetch_event_candidates(
        datetime(2026, 9, 13, tzinfo=KST),
        datetime(2026, 10, 13, tzinfo=KST),
    )

    assert "type: raid-hour" in result
    assert "title: Test Raid Hour" in result
    assert "start_at: 2026-09-16T18:00:00+09:00" in result
    assert "end_at: 2026-09-16T19:00:00+09:00" in result
    assert "https://leekduck.com/events/raid-1/" in result
