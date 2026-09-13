import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session

from app.collector import collect_events
from app.db import SessionLocal, ensure_schema
from app.event_service import current_events, events_between, next_event, remove_test_events
from app.models import Event
from app.scheduler import auto_collect_enabled, collection_loop
from app.schemas import MessageRequest


KST = ZoneInfo("Asia/Seoul")
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


app = FastAPI(title="Pokemon GO Kakao Bot", version="1.1.0", lifespan=lifespan)


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
    lines = [
        f"🎮 {event.title}",
        f"⏰ {start.strftime('%m/%d %H:%M')} ~ {end.strftime('%m/%d %H:%M')}",
    ]
    if event.pokemon:
        lines.append("✨ " + ", ".join(event.pokemon[:8]))
    if event.bonuses:
        lines.append("🎁 " + " / ".join(event.bonuses[:3]))
    if event.source_name:
        lines.append(f"🔗 {event.source_name}")
    return "\n".join(lines)


def event_reply(title: str, events: list[Event], empty: str) -> str:
    if not events:
        return empty
    return title + "\n\n" + "\n\n".join(format_event(event) for event in events)


@app.get("/")
def root():
    return {"name": "Pokemon GO Kakao Bot", "status": "running", "version": "1.0.0"}


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


@app.post("/api/messages")
def receive_message(data: MessageRequest, db: Session = Depends(get_db)):
    msg = " ".join(data.message.strip().split())
    now = datetime.now(KST)

    if "포고봇 테스트" in msg:
        return {"reply": "✅ Pokemon GO 봇 서버 연결 정상입니다."}
    if "포고봇 도움말" in msg:
        return {
            "reply": (
                "🤖 Pokemon GO 봇\n\n"
                "포고봇 오늘 / 내일 / 이번주\n"
                "포고봇 레이드 / 레이드아워\n"
                "포고봇 스포트라이트 / 커뮤\n"
                "포고봇 다음 이벤트 / 지금 뭐해\n"
                "포고봇 테스트"
            )
        }
    if "포고봇 지금" in msg:
        return {
            "reply": event_reply(
                "🎯 현재 진행 중인 일정",
                current_events(db, now),
                "현재 진행 중인 Pokemon GO 일정이 없습니다.",
            )
        }
    if "포고봇 다음" in msg:
        event = next_event(db, now)
        return {"reply": format_event(event) if event else "예정된 Pokemon GO 일정이 없습니다."}

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
        start, end = day_window()
        events = events_between(db, start, end)
        return {"reply": event_reply("📅 오늘의 Pokemon GO 일정", events, "📅 오늘 등록된 일정이 없습니다.")}
    if "포고봇 내일" in msg:
        start, end = day_window(1)
        events = events_between(db, start, end)
        return {"reply": event_reply("📅 내일의 Pokemon GO 일정", events, "📅 내일 등록된 일정이 없습니다.")}
    if "포고봇 이번주" in msg:
        start, _ = day_window()
        events = events_between(db, start, start + timedelta(days=7))
        return {"reply": event_reply("📅 앞으로 7일간 Pokemon GO 일정", events, "📅 앞으로 7일간 등록된 일정이 없습니다.")}
    return {"reply": None}
