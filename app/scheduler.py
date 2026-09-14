import asyncio
import logging
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.collector import collect_events
from app.db import SessionLocal
from app.tier_service import is_stale, refresh_tier_list


KST = ZoneInfo("Asia/Seoul")
LOGGER = logging.getLogger(__name__)
COLLECTION_HOURS = (6, 12, 18)


def auto_collect_enabled() -> bool:
    return os.getenv("AUTO_COLLECT_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def next_collection_at(now: datetime) -> datetime:
    now = now.astimezone(KST)
    for hour in COLLECTION_HOURS:
        candidate = datetime.combine(now.date(), time(hour=hour), tzinfo=KST)
        if candidate > now:
            return candidate
    return datetime.combine(
        now.date() + timedelta(days=1), time(hour=COLLECTION_HOURS[0]), tzinfo=KST
    )


def collect_once() -> None:
    with SessionLocal() as db:
        try:
            run = collect_events(db, days=30)
        except Exception:
            LOGGER.exception("scheduled event collection failed")
            return
        LOGGER.info(
            "scheduled event collection completed: found=%s inserted=%s updated=%s",
            run.found_count,
            run.inserted_count,
            run.updated_count,
        )


def refresh_tier_list_if_stale() -> None:
    """티어리스트는 게임 밸런스 패치 주기에 맞춰 한 달에 한 번만 갱신한다 -
    이벤트 수집(하루 3번)마다 매번 새로 긁을 필요는 없어서 갱신일만 체크한다.
    """
    with SessionLocal() as db:
        try:
            if is_stale(db):
                refresh_tier_list(db)
                LOGGER.info("tier list refreshed")
        except Exception:
            LOGGER.exception("tier list refresh failed")


async def collection_loop() -> None:
    while True:
        now = datetime.now(KST)
        scheduled_at = next_collection_at(now)
        delay = max(0.0, (scheduled_at - now).total_seconds())
        LOGGER.info("next scheduled event collection: %s", scheduled_at.isoformat())
        await asyncio.sleep(delay)
        await asyncio.to_thread(collect_once)
        await asyncio.to_thread(refresh_tier_list_if_stale)
