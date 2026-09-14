import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ADMIN_TOKEN"] = "test-admin-token"

from fastapi.testclient import TestClient

import app.main as main_module
from app import collector as collector_module
from app.db import Base, SessionLocal, engine
from app.event_service import upsert_event
from app.main import app
from app.models import TierList, utc_now
from app.schemas import CollectedEvent, CollectedEvents


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


def test_collect_auto_dedupes_cross_source_duplicate(monkeypatch):
    # 예전 수집에서 다른 출처(예: 지금은 안 쓰는 소스)로 저장된 행을 재현한다.
    shared_start = datetime.now(KST) + timedelta(hours=1)
    shared_end = shared_start + timedelta(hours=3)
    with SessionLocal() as db:
        db.add(
            main_module.Event(
                external_key="legacy-key",
                title="영문 제목",
                category="event",
                start_at=shared_start,
                end_at=shared_end,
                source_name="예전 소스",
                source_url="https://old-source.example/raid/",
                confidence=0.75,
            )
        )
        db.commit()

    fake_result = CollectedEvents(
        events=[
            CollectedEvent(
                title="한글 제목",
                category="event",
                start_at=shared_start,
                end_at=shared_end,
                source_name="공식 한국 뉴스",
                source_url="https://pokemongo.com/ko/news/sample",
                confidence=0.9,
            )
        ]
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        collector_module, "_collect_from_provider", lambda provider, prompt: fake_result
    )

    response = client.post(
        "/api/admin/collect", headers={"x-admin-token": "test-admin-token"}
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        titles = [
            e.title
            for e in db.query(main_module.Event)
            .filter(main_module.Event.title.in_(["영문 제목", "한글 제목"]))
            .all()
        ]
        assert titles == ["한글 제목"]


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


def test_delete_events_by_source_removes_only_matching_domain():
    leekduck_id = _add_event("리크덕 이벤트", source_url="https://leekduck.com/events/raid/")
    other_id = _add_event("다른 이벤트", source_url="https://pokemongo.com/ko/news/sample")

    response = client.delete(
        "/api/admin/events/source",
        params={"domain": "leekduck.com"},
        headers={"x-admin-token": "test-admin-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "completed", "removed": 1}
    with SessionLocal() as db:
        assert db.get(main_module.Event, leekduck_id) is None
        assert db.get(main_module.Event, other_id) is not None


def test_delete_events_by_source_requires_admin_token():
    event_id = _add_event("리크덕 이벤트", source_url="https://leekduck.com/events/raid/")

    response = client.delete("/api/admin/events/source", params={"domain": "leekduck.com"})

    assert response.status_code == 401
    with SessionLocal() as db:
        assert db.get(main_module.Event, event_id) is not None


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


def test_collect_command_acks_and_flags_await_collect(monkeypatch):
    response = message("포고봇 수집")
    body = response.json()

    assert "수집을 시작" in body["reply"]
    assert body["await_collect"] is True


def test_collect_command_rejects_when_already_running():
    with SessionLocal() as db:
        db.add(main_module.CollectRun(status="running"))
        db.commit()

    response = message("포고봇 수집")
    body = response.json()

    assert "이미 수집이 진행" in body["reply"]
    assert "await_collect" not in body


def test_collect_endpoint_runs_collection_and_reports_success(monkeypatch):
    class FakeRun:
        status = "completed"
        found_count = 3
        inserted_count = 1
        updated_count = 2

    monkeypatch.setattr(main_module, "collect_events", lambda db, days=30: FakeRun())

    response = client.post("/api/collect")

    assert "수집 완료" in response.json()["reply"]


def test_collect_endpoint_reports_failure(monkeypatch):
    def fake_collect(db, days=30):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "collect_events", fake_collect)

    response = client.post("/api/collect")

    assert "수집 실패" in response.json()["reply"]


def test_collect_endpoint_rejects_when_already_running():
    with SessionLocal() as db:
        db.add(main_module.CollectRun(status="running"))
        db.commit()

    response = client.post("/api/collect")

    assert "이미 수집이 진행" in response.json()["reply"]


def test_help_and_unknown_message():
    assert "레이드아워" in message("포고봇 도움말").json()["reply"]
    assert message("안녕하세요").json() == {"reply": None}


def test_type_matchup_command_returns_chart():
    reply = message("포고봇 상성 불꽃").json()["reply"]
    assert "불꽃 타입 상성" in reply
    assert "풀" in reply


def test_type_matchup_command_rejects_unknown_type():
    reply = message("포고봇 상성 없는타입").json()["reply"]
    assert "알아볼 수 없어요" in reply


def test_unmatched_pogo_command_acks_and_flags_await_ask(monkeypatch):
    response = message("포고봇 주간 릴레이 시간제한 리서치에는 뭐가 나와?")
    body = response.json()

    assert "확인하고 있어요" in body["reply"]
    assert body["await_ask"] is True


def test_ask_endpoint_runs_question_and_reports_answer(monkeypatch):
    monkeypatch.setattr(main_module, "answer_question", lambda question, context: "답변입니다")

    response = client.post(
        "/api/ask", json={"room": "test", "sender": "tester", "message": "질문"}
    )

    assert "답변입니다" in response.json()["reply"]


def test_ask_endpoint_includes_tier_data_for_tier_style_questions(monkeypatch):
    captured = {}

    def fake_answer_question(question, context):
        captured["context"] = context
        return "답변입니다"

    monkeypatch.setattr(main_module, "answer_question", fake_answer_question)
    monkeypatch.setattr(
        main_module, "get_tier_section", lambda db, korean_type: ["메가리자몽와이"]
    )

    client.post(
        "/api/ask",
        json={"room": "test", "sender": "tester", "message": "불꽃 타입 최고 포켓몬 뭐야?"},
    )

    assert "메가리자몽와이" in captured["context"]


def test_ask_endpoint_skips_tier_lookup_for_non_tier_questions(monkeypatch):
    calls = []
    monkeypatch.setattr(main_module, "answer_question", lambda question, context: "답변입니다")
    monkeypatch.setattr(
        main_module,
        "get_tier_section",
        lambda db, korean_type: calls.append(korean_type) or ["X"],
    )

    client.post(
        "/api/ask",
        json={"room": "test", "sender": "tester", "message": "불꽃 이벤트 언제 끝나?"},
    )

    assert calls == []


def test_tier_refresh_endpoint_requires_admin_token():
    response = client.post("/api/admin/tier-refresh", headers={"x-admin-token": "wrong"})
    assert response.status_code == 401


def test_tier_refresh_endpoint_stores_fetched_data(monkeypatch):
    monkeypatch.setattr(
        main_module,
        "refresh_tier_list",
        lambda db: db.add(TierList(id=1, data={"불꽃": ["X"]}, updated_at=utc_now())),
    )

    response = client.post(
        "/api/admin/tier-refresh", headers={"x-admin-token": "test-admin-token"}
    )

    assert response.status_code == 200
    assert response.json() == {"status": "refreshed"}


def test_ask_endpoint_reports_failure(monkeypatch):
    def fail(question, context):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "answer_question", fail)

    response = client.post(
        "/api/ask", json={"room": "test", "sender": "tester", "message": "질문"}
    )

    assert "답변 생성 실패" in response.json()["reply"]


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

    assert "🌏 Pokémon GO 와일드 에리어: 센다이, 도호쿠" in reply


def test_korean_event_keeps_plain_marker():
    _add("수확 축제: 과사삭벌레 모으기")

    reply = message("포고봇 다음 이벤트").json()["reply"]

    assert "🎮 수확 축제: 과사삭벌레 모으기" in reply


def test_next_events_dedupes_and_caps_at_three():
    shared_start = datetime.now(KST) + timedelta(hours=1)
    _add_event("이벤트A", start=shared_start, source_url="https://pokemongolive.com/a1")
    # 같은 category/start/end의 다른 출처 행 - 중복으로 취급돼 안 나와야 한다
    _add_event("이벤트A-복사", start=shared_start, source_url="https://pokemongolive.com/a2")
    _add_event("이벤트B", hours_from_now=2)
    _add_event("이벤트C", hours_from_now=3)
    _add_event("이벤트D", hours_from_now=4)

    reply = message("포고봇 다음 이벤트").json()["reply"]

    assert "이벤트A" in reply and "이벤트A-복사" not in reply
    assert "이벤트B" in reply
    assert "이벤트C" in reply
    assert "이벤트D" not in reply


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
