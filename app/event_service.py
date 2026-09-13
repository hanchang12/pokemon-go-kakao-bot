import hashlib
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Event, utc_now
from app.schemas import CollectedEvent


def make_external_key(event: CollectedEvent) -> str:
    normalized = "|".join(
        [event.title.strip().casefold(), event.category, event.start_at.isoformat()]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def remove_test_events(db: Session) -> int:
    result = db.execute(delete(Event).where(Event.source_name == "TEST"))
    return int(result.rowcount or 0)


def upsert_event(db: Session, item: CollectedEvent) -> tuple[Event, bool]:
    key = make_external_key(item)
    event = db.scalar(select(Event).where(Event.external_key == key))
    created = event is None
    if event is None:
        event = Event(external_key=key, created_at=utc_now())
        db.add(event)

    event.title = item.title.strip()
    event.category = item.category
    event.region = item.region
    event.start_at = item.start_at
    event.end_at = item.end_at
    event.description = item.description.strip()
    event.pokemon = item.pokemon
    event.bonuses = item.bonuses
    event.source_name = item.source_name.strip()
    event.source_url = str(item.source_url)
    event.confidence = item.confidence
    event.verified = item.confidence >= 0.8
    event.updated_at = utc_now()
    event.last_checked_at = utc_now()
    db.flush()
    return event, created


def events_between(
    db: Session,
    start_at: datetime,
    end_at: datetime,
    categories: set[str] | None = None,
) -> list[Event]:
    query = (
        select(Event)
        .where(Event.end_at > start_at)
        .where(Event.start_at < end_at)
        .order_by(Event.start_at, Event.title)
    )
    if categories:
        query = query.where(Event.category.in_(categories))
    return list(db.scalars(query).all())


def current_events(db: Session, now: datetime) -> list[Event]:
    query = (
        select(Event)
        .where(Event.start_at <= now)
        .where(Event.end_at > now)
        .order_by(Event.end_at, Event.title)
    )
    return list(db.scalars(query).all())


def next_event(db: Session, now: datetime) -> Event | None:
    query = (
        select(Event)
        .where(Event.start_at >= now)
        .order_by(Event.start_at, Event.title)
        .limit(1)
    )
    return db.scalar(query)
