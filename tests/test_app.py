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


def _add(title, *, region="kr", category="event", hours_from_now=1, duration=3):
    start = datetime.now(KST) + timedelta(hours=hours_from_now)
    item = CollectedEvent(
        title=title,
        category=category,
        region=region,
        start_at=start,
        end_at=start + timedelta(hours=duration),
        source_name="공식 한국 뉴스",
        source_url="https://pokemongo.com/ko/news/sample",
        confidence=0.9,
    )
    with SessionLocal() as db:
        upsert_event(db, item)
        db.commit()


def test_overseas_events_are_grouped_under_korean_ones():
    _add("수확 축제: 과사삭벌레 모으기")
    _add("Pokémon GO 와일드 에리어: 센다이, 도호쿠", region="overseas")

    reply = message("포고봇 이번주").json()["reply"]
    korean_at = reply.index("수확 축제: 과사삭벌레 모으기")
    header_at = reply.index("🌏 해외 전용 이벤트")
    overseas_at = reply.index("와일드 에리어")

    # 한국 일정이 먼저, 그 아래에 해외 전용 묶음이 온다
    assert korean_at < header_at < overseas_at
    assert reply.startswith("📅")


def test_overseas_only_week_still_shows_korean_section_note():
    _add("Pokémon GO 와일드 에리어: 센다이, 도호쿠", region="overseas")

    reply = message("포고봇 이번주").json()["reply"]

    assert "한국에서 참여할 수 있는 일정은 없습니다." in reply
    assert "🌏 해외 전용 이벤트" in reply


def test_overseas_event_is_marked_in_single_event_reply():
    _add("Pokémon GO 와일드 에리어: 센다이, 도호쿠", region="overseas")

    reply = message("포고봇 다음 이벤트").json()["reply"]

    assert reply.startswith("🌏")


def test_korean_event_keeps_plain_marker():
    _add("수확 축제: 과사삭벌레 모으기")

    reply = message("포고봇 다음 이벤트").json()["reply"]

    assert reply.startswith("🎮")


def test_command_list_is_served_by_both_names():
    listed = message("포고봇 리스트").json()["reply"]
    helped = message("포고봇 도움말").json()["reply"]

    assert listed == helped
    for command in ["포고봇 오늘", "포고봇 레이드아워", "포고봇 스포트라이트", "포고봇 테스트"]:
        assert command in listed
    assert "🌏" in listed
