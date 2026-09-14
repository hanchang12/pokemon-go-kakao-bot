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
    """같은 분류·시작·종료 시각의 이벤트가 여러 행으로 남아있을 때 가장 최근
    행(id가 가장 큰 행)만 남기고 나머지를 지운다.

    소스가 바뀌면(예: Leek Duck 영문 -> 공식 한국 뉴스 한글, 또는 커뮤니티 소스
    재수집 시 URL이 달라지는 경우) upsert_event의 source_url 기반 external_key도
    함께 바뀌어 예전 행이 그대로 남는다. 이 함수는 source_url이 달라도 실제로는
    같은 이벤트로 보이는 행(분류+시작+종료 시각이 완전히 같은 경우)을 정리한다.
    """
    newer = aliased(Event)
    older_ids = select(Event.id).join(
        newer,
        and_(
            Event.category == newer.category,
            Event.start_at == newer.start_at,
            Event.end_at == newer.end_at,
            Event.id < newer.id,
        ),
    )
    result = db.execute(delete(Event).where(Event.id.in_(older_ids)))
    db.flush()
    return int(result.rowcount or 0)


def delete_events_by_source_domain(db: Session, domain: str) -> int:
    """출처 URL에 domain이 포함된 이벤트를 전부 지운다 (예: 더 이상 안 쓰는 소스 정리)."""
    result = db.execute(delete(Event).where(Event.source_url.contains(domain)))
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


def next_events(db: Session, now: datetime, limit: int = 3) -> list[Event]:
    """앞으로 시작할 이벤트를 최대 limit개, 중복(같은 분류·시작·종료 시각) 없이 반환한다.

    같은 실제 이벤트가 소스가 달라 별도 행으로 남아 있을 수 있어(예: 출처 URL이
    바뀐 경우), 여기서는 표시 시점에 한 번 더 걸러낸다.
    """
    query = select(Event).where(Event.start_at >= now).order_by(Event.start_at, Event.title)

    results: list[Event] = []
    seen: set[tuple] = set()
    for event in db.scalars(query):
        key = (event.category, event.start_at, event.end_at)
        if key in seen:
            continue
        seen.add(key)
        results.append(event)
        if len(results) >= limit:
            break
    return results
