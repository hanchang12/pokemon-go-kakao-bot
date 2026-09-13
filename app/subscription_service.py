import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Subscription

KST = ZoneInfo("Asia/Seoul")
TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_time_of_day(text: str) -> time | None:
    match = TIME_PATTERN.match(text.strip())
    if not match:
        return None
    return time(hour=int(match.group(1)), minute=int(match.group(2)))


def next_fire_from(send_time: time, now: datetime) -> datetime:
    """send_time 다음 발송 시각(오늘 지났으면 내일)을 KST 기준으로 계산한다."""
    now_kst = now.astimezone(KST)
    candidate = now_kst.replace(
        hour=send_time.hour, minute=send_time.minute, second=0, microsecond=0
    )
    if candidate <= now_kst:
        candidate += timedelta(days=1)
    return candidate


def upsert_subscription(
    db: Session, room: str, send_time: time, recurring: bool, now: datetime
) -> Subscription:
    subscription = db.scalar(select(Subscription).where(Subscription.room == room))
    next_fire_at = next_fire_from(send_time, now)
    if subscription is None:
        subscription = Subscription(room=room)
        db.add(subscription)
    subscription.recurring = recurring
    subscription.send_time = send_time.strftime("%H:%M")
    subscription.next_fire_at = next_fire_at
    db.flush()
    return subscription


def cancel_subscription(db: Session, room: str) -> bool:
    subscription = db.scalar(select(Subscription).where(Subscription.room == room))
    if subscription is None:
        return False
    db.delete(subscription)
    db.flush()
    return True


def get_subscription(db: Session, room: str) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.room == room))


def due_subscriptions(db: Session, now: datetime) -> list[Subscription]:
    query = select(Subscription).where(Subscription.next_fire_at <= now)
    return list(db.scalars(query).all())


def mark_fired(db: Session, subscription: Subscription, now: datetime) -> None:
    """발송 처리: 정기 예약은 다음 발송 시각으로 미루고, 1회성은 지운다.

    폴링이 늦어져 next_fire_at이 여러 날 지나 있어도 한 번만 보내도록, 미래
    시각이 될 때까지 하루씩 건너뛴다(밀린 날짜만큼 중복 발송하지 않음).
    """
    if not subscription.recurring:
        db.delete(subscription)
        db.flush()
        return
    next_fire_at = subscription.next_fire_at
    if next_fire_at.tzinfo is None:
        # SQLite drops tzinfo on read (values are always written KST-aware);
        # Postgres returns it intact, so this is a no-op there.
        next_fire_at = next_fire_at.replace(tzinfo=KST)
    while next_fire_at <= now:
        next_fire_at += timedelta(days=1)
    subscription.next_fire_at = next_fire_at
    db.flush()
