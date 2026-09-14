import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ADMIN_TOKEN"] = "test-admin-token"

from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.event_service import upsert_event
from app.main import app
from app.models import Subscription
from app.schemas import CollectedEvent


KST = ZoneInfo("Asia/Seoul")
client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def message(text: str, room: str = "테스트방"):
    return client.post(
        "/api/messages",
        json={"room": room, "sender": "tester", "message": text},
    )


def test_reserve_once_registers_a_subscription():
    response = message("포고봇 예약 09:00")

    assert response.status_code == 200
    reply = response.json()["reply"]
    assert "1회" in reply
    assert "09:00" in reply
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="테스트방").one()
        assert subscription.recurring is False
        assert subscription.send_time == "09:00"


def test_reserve_daily_registers_a_recurring_subscription():
    response = message("포고봇 예약 매일 09:00")

    assert response.status_code == 200
    assert "매일" in response.json()["reply"]
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="테스트방").one()
        assert subscription.recurring is True


def test_reserve_invalid_time_is_rejected():
    response = message("포고봇 예약 매일 25:00")

    assert "00:00~23:59" in response.json()["reply"]
    with SessionLocal() as db:
        assert db.query(Subscription).filter_by(room="테스트방").first() is None


def test_reserve_bad_format_shows_usage():
    response = message("포고봇 예약 아무때나")

    assert "형식" in response.json()["reply"]


def test_reserve_status_reports_none_when_unset():
    response = message("포고봇 예약확인")

    assert response.json()["reply"] == "등록된 예약이 없습니다."


def test_reserve_status_reports_existing_subscription():
    message("포고봇 예약 매일 09:00")

    response = message("포고봇 예약확인")

    reply = response.json()["reply"]
    assert "매일" in reply
    assert "09:00" in reply


def test_reserve_cancel_removes_subscription():
    message("포고봇 예약 09:00")

    response = message("포고봇 예약취소")

    assert "취소" in response.json()["reply"]
    with SessionLocal() as db:
        assert db.query(Subscription).filter_by(room="테스트방").first() is None


def test_reserve_cancel_without_subscription_says_so():
    response = message("포고봇 예약취소")

    assert response.json()["reply"] == "등록된 예약이 없습니다."


def test_reserve_raid_hour_registers_separately_from_digest():
    message("포고봇 예약 09:00")

    response = message("포고봇 예약 레이드아워 17:50")

    reply = response.json()["reply"]
    assert "레이드아워" in reply
    assert "매주" in reply
    with SessionLocal() as db:
        subscriptions = db.query(Subscription).filter_by(room="테스트방").all()
        kinds = {sub.kind for sub in subscriptions}
        assert kinds == {"digest", "raid_hour"}


def test_reserve_spotlight_hour_registers_separately():
    response = message("포고봇 예약 스포트라이트 18:00")

    reply = response.json()["reply"]
    assert "스포트라이트" in reply
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="테스트방", kind="spotlight_hour").one()
        assert subscription.send_time == "18:00"


def test_reserve_status_lists_every_kind_registered():
    message("포고봇 예약 09:00")
    message("포고봇 예약 레이드아워 17:50")

    response = message("포고봇 예약확인")

    reply = response.json()["reply"]
    assert "오늘 일정" in reply
    assert "레이드아워" in reply


def test_reserve_cancel_with_kind_removes_only_that_kind():
    message("포고봇 예약 09:00")
    message("포고봇 예약 레이드아워 17:50")

    response = message("포고봇 예약취소 레이드아워")

    assert "레이드아워" in response.json()["reply"]
    with SessionLocal() as db:
        subscriptions = db.query(Subscription).filter_by(room="테스트방").all()
        assert {sub.kind for sub in subscriptions} == {"digest"}


def test_reserve_cancel_without_kind_removes_all():
    message("포고봇 예약 09:00")
    message("포고봇 예약 레이드아워 17:50")

    response = message("포고봇 예약취소")

    assert "전체" in response.json()["reply"]
    with SessionLocal() as db:
        assert db.query(Subscription).filter_by(room="테스트방").first() is None


def test_reserve_per_room_is_independent():
    message("포고봇 예약 09:00", room="방1")
    message("포고봇 예약 매일 20:00", room="방2")

    with SessionLocal() as db:
        room1 = db.query(Subscription).filter_by(room="방1").one()
        room2 = db.query(Subscription).filter_by(room="방2").one()
        assert room1.recurring is False and room1.send_time == "09:00"
        assert room2.recurring is True and room2.send_time == "20:00"


def _add_event(title, hours_from_now=1, category="event"):
    start = datetime.now(KST) + timedelta(hours=hours_from_now)
    item = CollectedEvent(
        title=title,
        category=category,
        start_at=start,
        end_at=start + timedelta(hours=3),
        source_name="Pokemon GO Live",
        source_url="https://pokemongolive.com/sample",
        confidence=1,
    )
    with SessionLocal() as db:
        upsert_event(db, item)
        db.commit()


def test_due_subscriptions_are_delivered_and_one_time_ones_are_removed():
    _add_event("오늘 이벤트")
    message("포고봇 예약 09:00", room="방1")
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="방1").one()
        subscription.next_fire_at = datetime.now(KST) - timedelta(minutes=1)
        db.commit()

    response = client.get("/api/subscriptions/due")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["room"] == "방1"
    assert "오늘 이벤트" in body["items"][0]["message"]
    with SessionLocal() as db:
        assert db.query(Subscription).filter_by(room="방1").first() is None


def test_due_recurring_subscription_is_rescheduled_not_deleted():
    message("포고봇 예약 매일 09:00", room="방1")
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="방1").one()
        subscription.next_fire_at = datetime.now(KST) - timedelta(minutes=1)
        db.commit()

    response = client.get("/api/subscriptions/due")

    assert response.json()["count"] == 1
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="방1").one()
        next_fire_at = subscription.next_fire_at
        if next_fire_at.tzinfo is None:  # SQLite drops tzinfo on read
            next_fire_at = next_fire_at.replace(tzinfo=KST)
        assert next_fire_at > datetime.now(KST)


def test_not_yet_due_subscription_is_not_delivered():
    message("포고봇 예약 매일 09:00", room="방1")

    response = client.get("/api/subscriptions/due")

    assert response.json()["count"] == 0


def test_due_raid_hour_subscription_only_includes_raid_hour_events():
    _add_event("일반 이벤트", category="event")
    _add_event("레이드아워 이벤트", category="raid_hour")
    message("포고봇 예약 레이드아워 09:00", room="방1")
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="방1", kind="raid_hour").one()
        subscription.next_fire_at = datetime.now(KST) - timedelta(minutes=1)
        db.commit()

    response = client.get("/api/subscriptions/due")

    body = response.json()
    assert body["count"] == 1
    reply = body["items"][0]["message"]
    assert "레이드아워 이벤트" in reply
    assert "일반 이벤트" not in reply


def test_due_recurring_raid_hour_reschedules_a_week_ahead():
    message("포고봇 예약 레이드아워 매일 09:00", room="방1")
    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="방1", kind="raid_hour").one()
        # 정상적으로 계산된 다음 수요일에서 정확히 1주 전으로 돌려, 요일 정렬은
        # 유지한 채 "지난 예약"만 흉내낸다(임의 시각으로 덮으면 요일이 깨진다).
        subscription.next_fire_at = subscription.next_fire_at - timedelta(days=7)
        db.commit()

    client.get("/api/subscriptions/due")

    with SessionLocal() as db:
        subscription = db.query(Subscription).filter_by(room="방1", kind="raid_hour").one()
        next_fire_at = subscription.next_fire_at
        if next_fire_at.tzinfo is None:
            next_fire_at = next_fire_at.replace(tzinfo=KST)
        assert next_fire_at.weekday() == 2  # Wednesday
