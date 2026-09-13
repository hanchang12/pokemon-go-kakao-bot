import hashlib
from datetime import datetime

from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session, aliased

from app.models import Event, utc_now
from app.schemas import CollectedEvent


def make_external_key(event: CollectedEvent) -> str:
    # source_url instead of title: the same event's title can be re-worded between
    # collector runs (e.g. Leek Duck English -> official Korean), and keying on title
    # would then treat it as a new event instead of updating the existing one.
    normalized = "|".join(
        [str(event.source_url).strip().casefold(), event.category, event.start_at.isoformat()]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def remove_test_events(db: Session) -> int:
    result = db.execute(delete(Event).where(Event.source_name == "TEST"))
    return int(result.rowcount or 0)


def delete_event(db: Session, event_id: int) -> bool:
    result = db.execute(delete(Event).where(Event.id == event_id))
    db.flush()
    return bool(result.rowcount)


def delete_duplicate_events(db: Session) -> int:
    """같은 이벤트(source_url+category+start_at+end_at)가 여러 행으로 남아있을 때
    가장 최근 행(id가 가장 큰 행)만 남기고 나머지를 지운다.

    소스가 바뀌어도(예: Leek Duck 영문 -> 공식 한국 뉴스 한글) upsert_event는
    source_url 기반 external_key로 갱신하지만, 소스 자체가 바뀐 이벤트는
    external_key도 함께 바뀌어 예전 행이 그대로 남는다. 이 함수는 그렇게 남은
    옛 행을 정리한다.
    """
    newer = aliased(Event)
    older_ids = select(Event.id).join(
        newer,
        and_(
            Event.source_url == newer.source_url,
            Event.category == newer.category,
            Event.start_at == newer.start_at,
            Event.end_at == newer.end_at,
            Event.id < newer.id,
        ),
    )
    result = db.execute(delete(Event).where(Event.id.in_(older_ids)))
    db.flush()
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
