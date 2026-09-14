import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Subscription

KST = ZoneInfo("Asia/Seoul")
TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

# 레이드아워/스포트라이트는 게임 내에서 요일이 고정돼 있어서(매주 수/목),
# 예약도 그 요일에만 돌아오도록 고정한다. Monday=0 기준.
KIND_WEEKDAY = {"raid_hour": 2, "spotlight_hour": 3}


def parse_time_of_day(text: str) -> time | None:
    match = TIME_PATTERN.match(text.strip())
    if not match:
        return None
    return time(hour=int(match.group(1)), minute=int(match.group(2)))


def next_fire_from(kind: str, send_time: time, now: datetime) -> datetime:
    """send_time 다음 발송 시각을 KST 기준으로 계산한다.

    요일이 고정된 kind(레이드아워/스포트라이트)는 그 요일 중 가장 가까운
    다음 시각으로, 그 외(digest)는 기존처럼 오늘 지났으면 내일로 넘어간다.
    """
    now_kst = now.astimezone(KST)
    candidate = now_kst.replace(
        hour=send_time.hour, minute=send_time.minute, second=0, microsecond=0
    )
    target_weekday = KIND_WEEKDAY.get(kind)
    if target_weekday is not None:
        days_ahead = (target_weekday - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= now_kst:
            candidate += timedelta(days=7)
        return candidate
    if candidate <= now_kst:
        candidate += timedelta(days=1)
    return candidate


def upsert_subscription(
    db: Session, room: str, kind: str, send_time: time, recurring: bool, now: datetime
) -> Subscription:
    subscription = db.scalar(
        select(Subscription).where(Subscription.room == room, Subscription.kind == kind)
    )
    next_fire_at = next_fire_from(kind, send_time, now)
    if subscription is None:
        subscription = Subscription(room=room, kind=kind)
        db.add(subscription)
    subscription.recurring = recurring
    subscription.send_time = send_time.strftime("%H:%M")
    subscription.next_fire_at = next_fire_at
    db.flush()
    return subscription


def cancel_subscription(db: Session, room: str, kind: str | None = None) -> int:
    """kind를 지정하면 그 종류만, 생략하면 방의 모든 예약을 취소하고 삭제 개수를 반환한다."""
    query = select(Subscription).where(Subscription.room == room)
    if kind is not None:
        query = query.where(Subscription.kind == kind)
    subscriptions = list(db.scalars(query).all())
    for subscription in subscriptions:
        db.delete(subscription)
    db.flush()
    return len(subscriptions)


def get_subscriptions(db: Session, room: str) -> list[Subscription]:
    return list(db.scalars(select(Subscription).where(Subscription.room == room)).all())


def due_subscriptions(db: Session, now: datetime) -> list[Subscription]:
    query = select(Subscription).where(Subscription.next_fire_at <= now)
    return list(db.scalars(query).all())


def mark_fired(db: Session, subscription: Subscription, now: datetime) -> None:
    """발송 처리: 정기 예약은 다음 발송 시각으로 미루고, 1회성은 지운다.

    폴링이 늦어져 next_fire_at이 여러 날 지나 있어도 한 번만 보내도록, 미래
    시각이 될 때까지 주기(요일 고정 kind는 7일, 그 외엔 1일)씩 건너뛴다.
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
    step = timedelta(days=7) if subscription.kind in KIND_WEEKDAY else timedelta(days=1)
    while next_fire_at <= now:
        next_fire_at += step
    subscription.next_fire_at = next_fire_at
    db.flush()
