import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ADMIN_TOKEN"] = "test-admin-token"

from fastapi.testclient import TestClient

import app.main as main_module
from app.db import Base, SessionLocal, engine
from app.event_service import upsert_event
from app.main import app
from app.schemas import CollectedEvent


KST = ZoneInfo("Asia/Seoul")
client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def message(text: str):
    return client.post(
        "/api/messages",
        json={"room": "test", "sender": "tester", "message": text},
    )


def test_admin_endpoint_rejects_bad_token():
    response = client.post(
        "/api/admin/collect", headers={"x-admin-token": "wrong"}
    )
    assert response.status_code == 401


def test_legacy_test_events_are_removed():
    start = datetime.now(KST) + timedelta(hours=1)
    with SessionLocal() as db:
        db.add(
            main_module.Event(
                title="테스트 레이드아워",
                category="raid_hour",
                start_at=start,
                end_at=start + timedelta(hours=1),
                source_name="TEST",
            )
        )
        db.commit()

    assert main_module.clean_legacy_test_events() == 1
    with SessionLocal() as db:
        assert db.query(main_module.Event).count() == 0


def test_category_command_and_next_event():
    start = datetime.now(KST) + timedelta(hours=1)
    item = CollectedEvent(
        title="테스트 커뮤니티 데이",
        category="community_day",
        start_at=start,
        end_at=start + timedelta(hours=3),
        source_name="Pokemon GO Live",
        source_url="https://pokemongolive.com/",
        confidence=1,
    )
    with SessionLocal() as db:
        upsert_event(db, item)
        db.commit()

    community = message("포고봇 커뮤")
    upcoming = message("포고봇 다음 이벤트")

    assert community.status_code == 200
    assert "테스트 커뮤니티 데이" in community.json()["reply"]
    assert "테스트 커뮤니티 데이" in upcoming.json()["reply"]


def test_help_and_unknown_message():
    assert "레이드아워" in message("포고봇 도움말").json()["reply"]
    assert message("안녕하세요").json() == {"reply": None}


def test_collection_provider_error_is_safe_and_actionable(monkeypatch):
    secret = "sensitive-test-api-key"
    monkeypatch.setenv("GEMINI_API_KEY", secret)

    def fail_collection(db, days):
        raise OSError(f"upstream request failed for {secret}")

    monkeypatch.setattr(main_module, "collect_events", fail_collection)
    response = client.post(
        "/api/admin/collect?days=30",
        headers={"x-admin-token": "test-admin-token"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "collection provider failed: OSError: "
        "upstream request failed for [redacted]"
    )
    assert secret not in response.text
