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


def _add_event(title, *, source_url="https://pokemongolive.com/sample", hours_from_now=1, start=None):
    start = start or datetime.now(KST) + timedelta(hours=hours_from_now)
    item = CollectedEvent(
        title=title,
        category="event",
        start_at=start,
        end_at=start + timedelta(hours=3),
        source_name="Pokemon GO Live",
        source_url=source_url,
        confidence=1,
    )
    with SessionLocal() as db:
        event, _ = upsert_event(db, item)
        db.commit()
        return event.id


def test_delete_event_by_id_removes_it():
    event_id = _add_event("삭제될 이벤트")

    response = client.delete(
        f"/api/admin/events/{event_id}", headers={"x-admin-token": "test-admin-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "id": event_id}
    with SessionLocal() as db:
        assert db.get(main_module.Event, event_id) is None


def test_delete_event_by_id_404_when_missing():
    response = client.delete(
        "/api/admin/events/999999", headers={"x-admin-token": "test-admin-token"}
    )

    assert response.status_code == 404


def test_delete_event_by_id_requires_admin_token():
    event_id = _add_event("보호될 이벤트")

    response = client.delete(f"/api/admin/events/{event_id}")

    assert response.status_code == 401
    with SessionLocal() as db:
        assert db.get(main_module.Event, event_id) is not None


def test_dedupe_removes_older_duplicate_and_keeps_newer():
    # upsert_event는 source_url/category/start_at이 같으면 같은 external_key를
    # 만들어 한 행으로 합치므로, 이미 서로 다른 external_key로 저장된 옛 중복
    # 행(예: 코드 수정 전 title 기반 키로 만들어진 레거시 행)을 직접 재현한다.
    shared_start = datetime.now(KST) + timedelta(hours=1)
    shared_end = shared_start + timedelta(hours=3)
    with SessionLocal() as db:
        old = main_module.Event(
            external_key="legacy-key-old",
            title="영문 제목",
            category="event",
            start_at=shared_start,
            end_at=shared_end,
            source_name="Leek Duck",
            source_url="https://leekduck.com/events/raid/",
            confidence=0.75,
        )
        new = main_module.Event(
            external_key="legacy-key-new",
            title="한글 제목",
            category="event",
            start_at=shared_start,
            end_at=shared_end,
            source_name="공식 한국 뉴스",
            source_url="https://leekduck.com/events/raid/",
            confidence=0.9,
        )
        db.add_all([old, new])
        db.commit()
        db.refresh(old)
        db.refresh(new)
        old_id, new_id = old.id, new.id
    other_id = _add_event("무관한 이벤트", source_url="https://leekduck.com/events/other/")

    response = client.delete(
        "/api/admin/events/dedupe", headers={"x-admin-token": "test-admin-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "completed", "removed": 1}
    with SessionLocal() as db:
        assert db.get(main_module.Event, old_id) is None
        assert db.get(main_module.Event, new_id) is not None
        assert db.get(main_module.Event, other_id) is not None


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


class _SyncThread:
    """threading.Thread를 대신해 target을 즉시 동기 실행하는 테스트용 더블."""

    def __init__(self, target=None, args=(), daemon=None):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


def test_collect_command_runs_in_background_and_reports_success(monkeypatch):
    class FakeRun:
        status = "completed"
        found_count = 3
        inserted_count = 1
        updated_count = 2

    monkeypatch.setattr(main_module, "collect_events", lambda db, days=30: FakeRun())
    monkeypatch.setattr(main_module.threading, "Thread", _SyncThread)

    response = message("포고봇 수집")

    assert "수집을 시작" in response.json()["reply"]
    due_items = client.get("/api/subscriptions/due").json()["items"]
    assert any("수집 완료" in item["message"] for item in due_items)


def test_collect_command_reports_failure(monkeypatch):
    def fake_collect(db, days=30):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "collect_events", fake_collect)
    monkeypatch.setattr(main_module.threading, "Thread", _SyncThread)

    message("포고봇 수집")

    due_items = client.get("/api/subscriptions/due").json()["items"]
    assert any("수집 실패" in item["message"] for item in due_items)


def test_collect_command_rejects_when_already_running():
    with SessionLocal() as db:
        db.add(main_module.CollectRun(status="running"))
        db.commit()

    response = message("포고봇 수집")

    assert "이미 수집이 진행" in response.json()["reply"]


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


def _add(
    title,
    *,
    region="kr",
    category="event",
    hours_from_now=1,
    duration=3,
    source_name="공식 한국 뉴스",
    source_url="https://pokemongo.com/ko/news/sample",
):
    start = datetime.now(KST) + timedelta(hours=hours_from_now)
    item = CollectedEvent(
        title=title,
        category=category,
        region=region,
        start_at=start,
        end_at=start + timedelta(hours=duration),
        source_name=source_name,
        source_url=source_url,
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


def test_official_korean_source_is_listed_before_other_sources():
    _add(
        "메가 레이드: 메가독침붕",
        hours_from_now=2,
        source_name="Leek Duck",
        source_url="https://leekduck.com/events/mega-beedrill/",
    )
    _add(
        "주간 릴레이 시간제한 리서치: 파트1",
        hours_from_now=1,
        source_name="공식 한국 뉴스",
        source_url="https://pokemongo.com/ko/news/weekly-branching-tr-korea-2026",
    )

    reply = message("포고봇 이번주").json()["reply"]
    header_at = reply.index("🇰🇷 한국 이벤트")
    official_at = reply.index("주간 릴레이 시간제한 리서치: 파트1")
    other_at = reply.index("메가 레이드: 메가독침붕")

    # 공식 한국 뉴스 출처가 먼저, 다른 출처(Leek Duck 등)가 그 다음
    assert header_at < official_at < other_at


def test_command_list_is_served_by_both_names():
    listed = message("포고봇 리스트").json()["reply"]
    helped = message("포고봇 도움말").json()["reply"]

    assert listed == helped
    for command in ["포고봇 오늘", "포고봇 레이드아워", "포고봇 스포트라이트", "포고봇 테스트"]:
        assert command in listed
    assert "🌏" in listed
