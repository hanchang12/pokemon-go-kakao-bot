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
