import os
from datetime import timedelta

os.environ["DATABASE_URL"] = "sqlite://"

from app.db import Base, SessionLocal, engine
from app.models import TierList, utc_now
from app.tier_service import get_tier_section, is_stale, refresh_tier_list


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_is_stale_true_when_no_row_exists():
    with SessionLocal() as db:
        assert is_stale(db) is True


def test_is_stale_false_for_recent_row():
    with SessionLocal() as db:
        db.add(TierList(id=1, data={}, updated_at=utc_now()))
        db.commit()
        assert is_stale(db) is False


def test_is_stale_true_after_30_days():
    with SessionLocal() as db:
        db.add(TierList(id=1, data={}, updated_at=utc_now() - timedelta(days=31)))
        db.commit()
        assert is_stale(db) is True


def test_refresh_tier_list_stores_fetched_data(monkeypatch):
    import app.tier_service as tier_service_module

    monkeypatch.setattr(
        tier_service_module, "fetch_tier_list", lambda: {"불꽃": ["Mega Charizard Y"]}
    )

    with SessionLocal() as db:
        refresh_tier_list(db)
        assert get_tier_section(db, "불꽃") == ["Mega Charizard Y"]
        assert is_stale(db) is False


def test_refresh_tier_list_overwrites_existing_row(monkeypatch):
    import app.tier_service as tier_service_module

    with SessionLocal() as db:
        db.add(TierList(id=1, data={"불꽃": ["Old Pokemon"]}, updated_at=utc_now() - timedelta(days=40)))
        db.commit()

    monkeypatch.setattr(
        tier_service_module, "fetch_tier_list", lambda: {"불꽃": ["New Pokemon"]}
    )

    with SessionLocal() as db:
        refresh_tier_list(db)
        assert get_tier_section(db, "불꽃") == ["New Pokemon"]


def test_get_tier_section_missing_type_returns_none():
    with SessionLocal() as db:
        db.add(TierList(id=1, data={"불꽃": ["X"]}, updated_at=utc_now()))
        db.commit()
        assert get_tier_section(db, "물") is None
