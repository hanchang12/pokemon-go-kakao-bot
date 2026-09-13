from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx


KST = ZoneInfo("Asia/Seoul")
LEEKDUCK_EVENTS_URL = "https://leekduck.com/events/"


@dataclass
class SourceEvent:
    occurrence_id: str
    event_type: str = "event"
    title: str = ""
    url: str = ""
    start_at: str | None = None
    end_at: str | None = None
    local_time: bool = True


class LeekDuckEventParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: dict[str, SourceEvent] = {}
        self.current: SourceEvent | None = None
        self.span_depth = 0
        self.in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if tag == "span" and "event-header-item-wrapper" in classes:
            occurrence_id = values.get("data-event-occurrence-id")
            if not occurrence_id:
                return
            self.current = SourceEvent(
                occurrence_id=occurrence_id,
                event_type=values.get("data-event-type") or "event",
                start_at=values.get("data-event-start-date"),
                end_at=values.get("data-event-end-date"),
                local_time=values.get("data-event-local-time") == "true",
            )
            self.span_depth = 1
            self.title_parts = []
            return

        if self.current is None:
            return
        if tag == "span":
            self.span_depth += 1
        elif tag == "a" and values.get("href"):
            self.current.url = urljoin(LEEKDUCK_EVENTS_URL, values["href"])
        elif tag == "h2":
            self.in_title = True

    def handle_data(self, data: str):
        if self.current is not None and self.in_title:
            self.title_parts.append(data)

    def handle_endtag(self, tag: str):
        if self.current is None:
            return
        if tag == "h2":
            self.in_title = False
            self.current.title = " ".join("".join(self.title_parts).split())
        if tag != "span":
            return

        self.span_depth -= 1
        if self.span_depth != 0:
            return

        existing = self.events.get(self.current.occurrence_id)
        if existing is None:
            self.events[self.current.occurrence_id] = self.current
        else:
            existing.event_type = self.current.event_type or existing.event_type
            existing.title = self.current.title or existing.title
            existing.url = self.current.url or existing.url
            existing.start_at = self.current.start_at or existing.start_at
            existing.end_at = self.current.end_at or existing.end_at
            existing.local_time = self.current.local_time
        self.current = None
        self.in_title = False
        self.title_parts = []


def _parse_time(value: str, local_time: bool) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        if not local_time:
            raise ValueError(f"source timestamp has no timezone: {value}")
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def fetch_event_candidates(now: datetime, until: datetime) -> str:
    response = httpx.get(
        LEEKDUCK_EVENTS_URL,
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "pokemon-go-kakao-bot/1.0"},
    )
    response.raise_for_status()

    parser = LeekDuckEventParser()
    parser.feed(response.text)
    lines = []
    for event in parser.events.values():
        if not event.title or not event.url or not event.start_at or not event.end_at:
            continue
        start_at = _parse_time(event.start_at, event.local_time)
        end_at = _parse_time(event.end_at, event.local_time)
        if end_at <= now or start_at >= until:
            continue
        lines.append(
            "\n".join(
                [
                    f"type: {event.event_type}",
                    f"title: {event.title}",
                    f"start_at: {start_at.isoformat()}",
                    f"end_at: {end_at.isoformat()}",
                    "source_name: Leek Duck",
                    f"source_url: {event.url}",
                ]
            )
        )
    if not lines:
        raise RuntimeError("No matching events were found in the public schedule")
    return "\n\n---\n\n".join(lines)
