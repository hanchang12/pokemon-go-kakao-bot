import asyncio
import hmac
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collector import collect_events
from app.db import SessionLocal, ensure_schema
from app.event_service import (
    current_events,
    delete_duplicate_events,
    delete_event,
    delete_events_by_source_domain,
    events_between,
    next_events,
    remove_test_events,
)
from app.models import CollectRun, Event
from app.outbox_service import enqueue_message, pop_outbox
from app.scheduler import auto_collect_enabled, collection_loop
from app.schemas import MessageRequest
from app.subscription_service import (
    cancel_subscription,
    due_subscriptions,
    get_subscription,
    mark_fired,
    parse_time_of_day,
    upsert_subscription,
)


KST = ZoneInfo("Asia/Seoul")
COMMAND_LIST = """🤖 포고봇 명령어

📅 일정
· 포고봇 오늘 / 내일 / 이번주
· 포고봇 지금 뭐해 — 현재 진행 중
· 포고봇 다음 이벤트 — 새로 시작할 일정 최대 3개

⚔️ 종류별
· 포고봇 레이드 — 앞으로 7일 레이드
· 포고봇 레이드아워 — 매주 수 18:00
· 포고봇 스포트라이트 — 매주 목 18:00
· 포고봇 커뮤 — 앞으로 30일 커뮤니티 데이

⏰ 예약
· 포고봇 예약 09:00 — 오늘/내일 09:00에 1회 발송
· 포고봇 예약 매일 09:00 — 매일 09:00에 정기 발송
· 포고봇 예약확인 — 이 방의 예약 상태 확인
· 포고봇 예약취소 — 이 방의 예약 취소

ℹ️ 기타
· 포고봇 수집 — 최신 이벤트 지금 수집 (완료되면 알려드려요)
· 포고봇 리스트 / 도움말 — 이 안내
· 포고봇 테스트 — 서버 연결 확인

일정은 공식 한국 사이트(pokemongo.com/ko) 기준입니다.
해외에서만 열리는 이벤트는 🌏 표시로 아래에 따로 묶어 보여줍니다."""
RESERVE_PATTERN = re.compile(r"포고봇\s*예약\s*(매일)?\s*(\d{1,2}:\d{2})")
LOGGER = logging.getLogger(__name__)
ensure_schema()


def clean_legacy_test_events() -> int:
    with SessionLocal() as db:
        deleted = remove_test_events(db)
        db.commit()
    if deleted:
        LOGGER.info("removed %s legacy test events", deleted)
    return deleted


@asynccontextmanager
async def lifespan(_: FastAPI):
    clean_legacy_test_events()
    task = asyncio.create_task(collection_loop()) if auto_collect_enabled() else None
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Pokemon GO Kakao Bot", version="1.2.0", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_TOKEN is not configured")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(status_code=401, detail="invalid admin token")


def safe_error_detail(exc: Exception) -> str:
    message = str(exc)
    for name in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "NVIDIA_API_KEY",
        "ADMIN_TOKEN",
    ):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    return f"{type(exc).__name__}: {message}"[:1000]


def day_window(offset: int = 0) -> tuple[datetime, datetime]:
    target = datetime.now(KST).date() + timedelta(days=offset)
    start = datetime.combine(target, time.min, tzinfo=KST)
    return start, start + timedelta(days=1)


def format_event(event: Event) -> str:
    start = event.start_at.astimezone(KST)
    end = event.end_at.astimezone(KST)
    marker = "🌏" if event.region == "overseas" else "🎮"
    lines = [
        f"{marker} {event.title}",
        f"⏰ {start.strftime('%m/%d %H:%M')} ~ {end.strftime('%m/%d %H:%M')}",
    ]
    if event.pokemon:
        lines.append("✨ " + ", ".join(event.pokemon[:8]))
    if event.bonuses:
        lines.append("🎁 " + " / ".join(event.bonuses[:3]))
    if event.source_name:
        lines.append(f"🔗 {event.source_name}")
    return "\n".join(lines)


KOREAN_HEADER = "🇰🇷 한국 이벤트"
OVERSEAS_HEADER = "───────────────\n🌏 해외 전용 이벤트"
OFFICIAL_KOREAN_SOURCE = "공식 한국 뉴스"


def event_reply(title: str, events: list[Event], empty: str) -> str:
    """한국 일정은 공식 한국 뉴스 소스를 먼저, 다른 소스를 그 다음에 보여주고, 해외 전용은 아래에 따로 묶는다."""
    korean = sorted(
        (event for event in events if event.region != "overseas"),
        key=lambda e: e.source_name != OFFICIAL_KOREAN_SOURCE,
    )
    overseas = [event for event in events if event.region == "overseas"]
    if not korean and not overseas:
        return empty

    sections = []
    if korean:
        sections.append(
            title + "\n\n" + KOREAN_HEADER + "\n\n" + "\n\n".join(format_event(e) for e in korean)
        )
    else:
        sections.append(f"{title}\n\n한국에서 참여할 수 있는 일정은 없습니다.")
    if overseas:
        sections.append(OVERSEAS_HEADER + "\n\n" + "\n\n".join(format_event(e) for e in overseas))
    return "\n\n".join(sections)


def today_digest(db: Session) -> str:
    start, end = day_window()
    events = events_between(db, start, end)
    return event_reply("📅 오늘의 Pokemon GO 일정", events, "📅 오늘 등록된 일정이 없습니다.")


def _collection_in_progress(db: Session) -> bool:
    latest = db.scalar(select(CollectRun).order_by(CollectRun.started_at.desc()).limit(1))
    return latest is not None and latest.status == "running"


def _run_collection_and_notify(room: str) -> None:
    """백그라운드 스레드에서 수집을 돌리고, 끝나면 outbox에 결과를 남긴다.

    카카오톡 요청-응답 왕복(메신저봇R의 12초 타임아웃)보다 수집이 오래 걸릴 수
    있어서, 명령을 받으면 즉시 응답하고 실제 수집은 별도 스레드에서 진행한다.
    완료 결과는 /api/subscriptions/due 폴링으로 같은 방에 전달된다.
    """
    with SessionLocal() as db:
        try:
            run = collect_events(db, days=30)
            message = (
                "✅ 이벤트 수집 완료\n"
                f"발견 {run.found_count} · 신규 {run.inserted_count} · 갱신 {run.updated_count}"
            )
        except Exception as exc:
            LOGGER.exception("수동 수집 실패")
            message = f"⚠️ 이벤트 수집 실패: {safe_error_detail(exc)}"
        enqueue_message(db, room, message)
        db.commit()


@app.get("/")
def root():
    return {"name": "Pokemon GO Kakao Bot", "status": "running", "version": app.version}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/db-check")
def db_check(db: Session = Depends(get_db)):
    try:
        db.connection().exec_driver_sql("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/admin/collect", dependencies=[Depends(require_admin)])
def run_collection(days: int = 30, db: Session = Depends(get_db)):
    try:
        run = collect_events(db, days=days)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"collection provider failed: {safe_error_detail(exc)}",
        ) from exc
    return {
        "status": run.status,
        "run_id": run.id,
        "found": run.found_count,
        "inserted": run.inserted_count,
        "updated": run.updated_count,
    }


@app.delete("/api/admin/events/dedupe", dependencies=[Depends(require_admin)])
def dedupe_events(db: Session = Depends(get_db)):
    removed = delete_duplicate_events(db)
    db.commit()
    return {"status": "completed", "removed": removed}


@app.delete("/api/admin/events/source", dependencies=[Depends(require_admin)])
def delete_events_by_source(domain: str, db: Session = Depends(get_db)):
    """더 이상 쓰지 않는 소스(예: leekduck.com)에서 온 이벤트를 전부 지운다."""
    removed = delete_events_by_source_domain(db, domain)
    db.commit()
    return {"status": "completed", "removed": removed}


@app.delete("/api/admin/events/{event_id}", dependencies=[Depends(require_admin)])
def delete_event_by_id(event_id: int, db: Session = Depends(get_db)):
    if not delete_event(db, event_id):
        raise HTTPException(status_code=404, detail="event not found")
    db.commit()
    return {"status": "deleted", "id": event_id}


@app.get("/api/events/today")
def events_today(db: Session = Depends(get_db)):
    start, end = day_window()
    events = events_between(db, start, end)
    return {
        "count": len(events),
        "events": [
            {
                "id": event.id,
                "title": event.title,
                "category": event.category,
                "start_at": event.start_at,
                "end_at": event.end_at,
                "source_url": event.source_url,
            }
            for event in events
        ],
    }


@app.get("/api/subscriptions/due")
def subscriptions_due(db: Session = Depends(get_db)):
    """메신저봇R 스크립트가 주기적으로 폴링해서 예약 발송을 가져가는 엔드포인트.

    서버는 카카오톡 방에 직접 메시지를 보낼 수 없어서(메신저봇R만 가능), 발송할
    내용을 여기 큐에 담아두면 스크립트가 폴링 후 각 방에 직접 전송한다.
    """
    now = datetime.now(KST)
    items = []
    for subscription in due_subscriptions(db, now):
        items.append({"room": subscription.room, "message": today_digest(db)})
        mark_fired(db, subscription, now)
    for pending in pop_outbox(db):
        items.append({"room": pending.room, "message": pending.message})
    db.commit()
    return {"count": len(items), "items": items}


@app.post("/api/messages")
def receive_message(data: MessageRequest, db: Session = Depends(get_db)):
    msg = " ".join(data.message.strip().split())
    now = datetime.now(KST)

    if "포고봇 테스트" in msg:
        return {"reply": "✅ Pokemon GO 봇 서버 연결 정상입니다."}
    if "포고봇 리스트" in msg or "포고봇 도움말" in msg:
        return {"reply": COMMAND_LIST}
    if "포고봇 지금" in msg:
        return {
            "reply": event_reply(
                "🎯 현재 진행 중인 일정",
                current_events(db, now),
                "현재 진행 중인 Pokemon GO 일정이 없습니다.",
            )
        }
    if "포고봇 다음" in msg:
        events = next_events(db, now, limit=3)
        return {"reply": event_reply("🔜 다음 이벤트", events, "예정된 Pokemon GO 일정이 없습니다.")}

    if "포고봇 수집" in msg:
        if _collection_in_progress(db):
            return {"reply": "⏳ 이미 수집이 진행 중이에요. 완료되면 알려드릴게요."}
        threading.Thread(
            target=_run_collection_and_notify, args=(data.room,), daemon=True
        ).start()
        return {"reply": "🔄 이벤트 수집을 시작했어요. 완료되면 알려드릴게요 (몇십 초~몇 분 정도 걸려요)."}

    if "포고봇 예약취소" in msg:
        cancelled = cancel_subscription(db, data.room)
        db.commit()
        return {"reply": "🗑️ 이 방의 예약을 취소했습니다." if cancelled else "등록된 예약이 없습니다."}

    if "포고봇 예약확인" in msg:
        subscription = get_subscription(db, data.room)
        if subscription is None:
            return {"reply": "등록된 예약이 없습니다."}
        kind = "매일" if subscription.recurring else "1회"
        next_at = subscription.next_fire_at.astimezone(KST).strftime("%m/%d %H:%M")
        return {
            "reply": f"⏰ {kind} {subscription.send_time} 예약 중\n다음 발송: {next_at}"
        }

    if "포고봇 예약" in msg:
        match = RESERVE_PATTERN.search(msg)
        if not match:
            return {
                "reply": (
                    "⏰ 예약 시간 형식이 올바르지 않습니다.\n"
                    "포고봇 예약 09:00 (1회)\n"
                    "포고봇 예약 매일 09:00 (정기)"
                )
            }
        send_time = parse_time_of_day(match.group(2))
        if send_time is None:
            return {"reply": "⏰ 예약 시간은 00:00~23:59 사이로 입력해 주세요."}
        recurring = match.group(1) is not None
        subscription = upsert_subscription(db, data.room, send_time, recurring, now)
        db.commit()
        kind = "매일" if recurring else "1회"
        next_at = subscription.next_fire_at.astimezone(KST).strftime("%m/%d %H:%M")
        return {
            "reply": (
                f"✅ {kind} {subscription.send_time}에 '포고봇 오늘' 목록을 보내드릴게요.\n"
                f"다음 발송: {next_at}"
            )
        }

    filters = [
        ("레이드아워", {"raid_hour"}, "⚔️ 앞으로 7일간 레이드아워"),
        ("스포트라이트", {"spotlight_hour"}, "🔦 앞으로 7일간 스포트라이트 아워"),
        ("커뮤", {"community_day"}, "👥 앞으로 30일간 커뮤니티 데이"),
        ("레이드", {"raid", "raid_hour"}, "⚔️ 앞으로 7일간 레이드 일정"),
    ]
    for keyword, categories, title in filters:
        if f"포고봇 {keyword}" in msg:
            days = 30 if keyword == "커뮤" else 7
            return {
                "reply": event_reply(
                    title,
                    events_between(db, now, now + timedelta(days=days), categories),
                    f"앞으로 {days}일간 해당 일정이 없습니다.",
                )
            }

    if "포고봇 오늘" in msg:
        return {"reply": today_digest(db)}
    if "포고봇 내일" in msg:
        start, end = day_window(1)
        events = events_between(db, start, end)
        return {"reply": event_reply("📅 내일의 Pokemon GO 일정", events, "📅 내일 등록된 일정이 없습니다.")}
    if "포고봇 이번주" in msg:
        start, _ = day_window()
        events = events_between(db, start, start + timedelta(days=7))
        return {"reply": event_reply("📅 앞으로 7일간 Pokemon GO 일정", events, "📅 앞으로 7일간 등록된 일정이 없습니다.")}
    return {"reply": None}
