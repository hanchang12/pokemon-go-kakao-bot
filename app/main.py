import asyncio
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collector import answer_question, collect_events
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
from app.outbox_service import pop_outbox
from app.pokeapi import fetch_evolution_chain_korean
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
from app.tier_service import get_tier_section, refresh_tier_list
from app.type_chart import ALL_TYPES, format_matchup


KST = ZoneInfo("Asia/Seoul")
COMMAND_LIST = """🤖 포고봇 명령어

📅 일정
· /포고봇 오늘 / 내일 / 이번주
· /포고봇 지금 뭐해 — 현재 진행 중
· /포고봇 다음 이벤트 — 새로 시작할 일정 최대 3개

⚔️ 종류별
· /포고봇 레이드 — 앞으로 7일 레이드
· /포고봇 레이드아워 — 매주 수 18:00
· /포고봇 스포트라이트 — 매주 목 18:00
· /포고봇 커뮤 — 앞으로 30일 커뮤니티 데이
· /포고봇 상성 [타입] — 타입 상성 (예: /포고봇 상성 불꽃)
· /포고봇 티어 [타입] — 타입별 상위 공격 포켓몬 (예: /포고봇 티어 불꽃)
· /포고봇 진화 [영문이름] — 진화 체인 (예: /포고봇 진화 charmander)

⏰ 예약
· /포고봇 예약 09:00 — 오늘/내일 09:00에 1회 발송
· /포고봇 예약 매일 09:00 — 매일 09:00에 정기 발송
· /포고봇 예약확인 — 이 방의 예약 상태 확인
· /포고봇 예약취소 — 이 방의 예약 취소

ℹ️ 기타
· /포고봇 수집 — 최신 이벤트 지금 수집 (완료되면 알려드려요)
· /포고봇 리스트 / 도움말 — 이 안내
· /포고봇 테스트 — 서버 연결 확인

일정은 공식 한국 사이트(pokemongo.com/ko) 기준입니다.
해외에서만 열리는 이벤트는 🌏 표시로 아래에 따로 묶어 보여줍니다.

위 명령어에 없는 질문도 "/포고봇 ..."으로 물어보면 등록된 일정을 근거로
AI가 답해드려요 (완료되면 알려드려요)."""
RESERVE_PATTERN = re.compile(r"포고봇\s*예약\s*(매일)?\s*(\d{1,2}:\d{2})")
TYPE_PATTERN = re.compile(r"포고봇\s*상성\s*(\S+)")
TIER_TYPE_PATTERN = re.compile(r"포고봇\s*티어\s*(\S+)")
EVOLUTION_PATTERN = re.compile(r"포고봇\s*진화\s*(\S+)")
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


def _run_collection(db: Session) -> str:
    """수집을 동기로 돌리고 카톡에 보낼 결과 문구를 반환한다."""
    try:
        run = collect_events(db, days=30)
        return (
            "✅ 이벤트 수집 완료\n"
            f"발견 {run.found_count} · 신규 {run.inserted_count} · 갱신 {run.updated_count}"
        )
    except Exception as exc:
        LOGGER.exception("채팅 수집 실패")
        return f"⚠️ 이벤트 수집 실패: {safe_error_detail(exc)}"


TIER_KEYWORDS = ("티어", "최고", "베스트", "순위", "탑", "추천")


def _answer_question(db: Session, question: str) -> str:
    """도움말에 없는 자유 질문에 답하고 카톡에 보낼 문구를 반환한다."""
    now = datetime.now(KST)
    events = events_between(db, now, now + timedelta(days=30))
    context = "\n\n".join(format_event(e) for e in events) or "등록된 일정 없음"

    # "불꽃 타입 최고 포켓몬" 같은 질문은 AI 자체 지식만으론 이름을 지어낼 수
    # 있어서(관측됨), 실제 티어리스트 캐시가 있으면 근거로 덧붙인다.
    if any(keyword in question for keyword in TIER_KEYWORDS):
        matched_type = next((t for t in ALL_TYPES if t in question), None)
        if matched_type:
            pokemon = get_tier_section(db, matched_type)
            if pokemon:
                context += (
                    f"\n\n{matched_type} 타입 상위 공격 포켓몬(실제 티어리스트 "
                    f"기준, 순위 순): {', '.join(pokemon)}"
                )

    try:
        return "🤖 " + answer_question(question, context)
    except Exception as exc:
        LOGGER.exception("AI 질문 답변 실패")
        return f"⚠️ 답변 생성 실패: {safe_error_detail(exc)}"


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


@app.post("/api/collect")
def collect_blocking(db: Session = Depends(get_db)):
    """"포고봇 수집" 채팅 명령의 두 번째(블로킹) 호출.

    첫 호출(/api/messages)이 즉시 응답으로 "시작했어요"를 준 직후, 폰 스크립트가
    바로 이어서 이 엔드포인트를 긴 타임아웃으로 호출해 실제 수집을 동기로 기다린다.
    완료/실패 결과가 같은 대화 흐름 안에서 바로 오도록 하기 위함 - 예전에는
    백그라운드 스레드 + outbox 폴링으로 전달했는데, 폴링이 다른 채팅 메시지가
    와야만 실행돼서 조용한 방에서는 결과가 영영 안 오는 문제가 있었다.
    """
    if _collection_in_progress(db):
        return {"reply": "⏳ 이미 수집이 진행 중이에요."}
    return {"reply": _run_collection(db)}


@app.post("/api/ask")
def ask_blocking(data: MessageRequest, db: Session = Depends(get_db)):
    """자유 질문 채팅 명령의 두 번째(블로킹) 호출. /api/collect와 같은 이유."""
    return {"reply": _answer_question(db, data.message)}


@app.post("/api/admin/tier-refresh", dependencies=[Depends(require_admin)])
def tier_refresh(db: Session = Depends(get_db)):
    """정기 수집(한 달 주기)을 기다리지 않고 티어리스트를 즉시 갱신한다."""
    try:
        refresh_tier_list(db)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"tier list fetch failed: {safe_error_detail(exc)}"
        ) from exc
    return {"status": "refreshed"}


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
        return {
            "reply": "🔄 이벤트 수집을 시작했어요. 완료되면 알려드릴게요 (몇십 초~몇 분 정도 걸려요).",
            "await_collect": True,
        }

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
                    "/포고봇 예약 09:00 (1회)\n"
                    "/포고봇 예약 매일 09:00 (정기)"
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
                f"✅ {kind} {subscription.send_time}에 '/포고봇 오늘' 목록을 보내드릴게요.\n"
                f"다음 발송: {next_at}"
            )
        }

    if "포고봇 상성" in msg:
        match = TYPE_PATTERN.search(msg)
        type_name = match.group(1) if match else ""
        reply_text = format_matchup(type_name)
        if reply_text is None:
            reply_text = "⚔️ 타입을 알아볼 수 없어요. 예: /포고봇 상성 불꽃\n(" + ", ".join(ALL_TYPES) + ")"
        return {"reply": reply_text}

    if "포고봇 티어" in msg:
        match = TIER_TYPE_PATTERN.search(msg)
        type_name = match.group(1) if match else ""
        if type_name not in ALL_TYPES:
            return {
                "reply": "🏆 타입을 알아볼 수 없어요. 예: /포고봇 티어 불꽃\n("
                + ", ".join(ALL_TYPES)
                + ")"
            }
        pokemon = get_tier_section(db, type_name)
        if not pokemon:
            return {"reply": "🏆 아직 티어리스트 데이터가 없어요. 잠시 후 다시 시도해주세요."}
        ranked = "\n".join(f"{i}. {name}" for i, name in enumerate(pokemon, start=1))
        return {"reply": f"🏆 {type_name} 타입 상위 공격 포켓몬\n{ranked}"}

    if "포고봇 진화" in msg:
        match = EVOLUTION_PATTERN.search(msg)
        species_name = match.group(1) if match else ""
        if not species_name:
            return {"reply": "🧬 포켓몬 영문 이름을 같이 입력해주세요. 예: /포고봇 진화 charmander"}
        stages = fetch_evolution_chain_korean(species_name)
        if not stages:
            return {
                "reply": f"🧬 '{species_name}'을(를) 찾을 수 없어요. 정확한 영문 이름으로 다시 시도해주세요."
            }
        chain_text = " → ".join("/".join(stage) for stage in stages)
        return {"reply": f"🧬 진화 체인\n{chain_text}"}

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

    if "포고봇" in msg:
        return {
            "reply": "🤖 질문을 확인하고 있어요. 잠시 후 답변 드릴게요 (몇십 초~몇 분 걸릴 수 있어요).",
            "await_ask": True,
        }
    return {"reply": None}
