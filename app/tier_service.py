from datetime import timedelta, timezone

from sqlalchemy.orm import Session

from app.models import TierList, utc_now
from app.tier_source import fetch_tier_list


REFRESH_INTERVAL_DAYS = 30
TIER_LIST_ROW_ID = 1


def get_tier_section(db: Session, korean_type: str) -> list[str] | None:
    row = db.get(TierList, TIER_LIST_ROW_ID)
    if row is None:
        return None
    return row.data.get(korean_type)


def is_stale(db: Session) -> bool:
    row = db.get(TierList, TIER_LIST_ROW_ID)
    if row is None:
        return True
    # SQLite는 DateTime(timezone=True) 컬럼을 tzinfo 없이 돌려준다 (Postgres는 안 그럼)
    updated_at = row.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return utc_now() - updated_at > timedelta(days=REFRESH_INTERVAL_DAYS)


def refresh_tier_list(db: Session) -> None:
    data = fetch_tier_list()
    row = db.get(TierList, TIER_LIST_ROW_ID)
    if row is None:
        db.add(TierList(id=TIER_LIST_ROW_ID, data=data, updated_at=utc_now()))
    else:
        row.data = data
        row.updated_at = utc_now()
    db.commit()
