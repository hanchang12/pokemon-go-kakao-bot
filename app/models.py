from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text

from app.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    external_key = Column(String(64), unique=True, index=True, nullable=True)
    title = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False, default="event")
    region = Column(String(20), nullable=False, default="kr")
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    description = Column(Text)
    pokemon = Column(JSON, nullable=True)
    bonuses = Column(JSON, nullable=True)
    source_name = Column(String(100))
    source_url = Column(Text)
    confidence = Column(Float)
    verified = Column(Boolean, nullable=True, default=False)
    created_at = Column(DateTime(timezone=True), nullable=True, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=True, default=utc_now, onupdate=utc_now)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    room = Column(String(200), nullable=False, unique=True)
    recurring = Column(Boolean, nullable=False, default=False)
    send_time = Column(String(5), nullable=False)  # "HH:MM", Asia/Seoul wall-clock
    next_fire_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class Outbox(Base):
    """폰의 메신저봇R 스크립트가 폴링해서 방에 직접 전달할 1회성 메시지 큐."""

    __tablename__ = "outbox"

    id = Column(Integer, primary_key=True)
    room = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class TierList(Base):
    """타입별 최고 공격 포켓몬 목록 캐시 (외부 티어리스트 사이트에서 월 1회 수집).

    항상 id=1 하나만 존재하는 싱글턴 행 - 게임 밸런스 패치로 바뀌는 데이터라
    매번 다시 긁지 않고 캐시해서 갱신일만 보고 갱신 여부를 판단한다.
    """

    __tablename__ = "tier_lists"

    id = Column(Integer, primary_key=True)
    data = Column(JSON, nullable=False)  # {"불꽃": ["Mega Blaziken", ...], ...}
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)


class CollectRun(Base):
    __tablename__ = "collect_runs"

    id = Column(Integer, primary_key=True)
    status = Column(String(20), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    finished_at = Column(DateTime(timezone=True))
    found_count = Column(Integer, nullable=False, default=0)
    inserted_count = Column(Integer, nullable=False, default=0)
    updated_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text)
