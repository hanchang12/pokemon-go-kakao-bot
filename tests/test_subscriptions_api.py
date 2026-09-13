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


def test_reserve_per_room_is_independent():
    message("포고봇 예약 09:00", room="방1")
    message("포고봇 예약 매일 20:00", room="방2")

    with SessionLocal() as db:
        room1 = db.query(Subscription).filter_by(room="방1").one()
        room2 = db.query(Subscription).filter_by(room="방2").one()
        assert room1.recurring is False and room1.send_time == "09:00"
        assert room2.recurring is True and room2.send_time == "20:00"


def _add_event(title, hours_from_now=1):
    start = datetime.now(KST) + timedelta(hours=hours_from_now)
    item = CollectedEvent(
        title=title,
        category="event",
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
