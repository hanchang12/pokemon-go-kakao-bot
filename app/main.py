import os
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    select,
)
from sqlalchemy.orm import declarative_base, sessionmaker


# --------------------------------------------------
# 기본 설정
# --------------------------------------------------

app = FastAPI(
    title="Pokemon GO Kakao Bot",
    version="0.4.0",
)

DATABASE_URL = os.environ["DATABASE_URL"]

KST = ZoneInfo("Asia/Seoul")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


# --------------------------------------------------
# DB Model
# --------------------------------------------------

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)

    title = Column(String(200), nullable=False)

    category = Column(
        String(50),
        nullable=False,
        default="event",
    )

    start_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    end_at = Column(
        DateTime(timezone=True),
        nullable=False,
    )

    description = Column(Text)

    source_name = Column(String(100))
    source_url = Column(Text)


Base.metadata.create_all(bind=engine)


# --------------------------------------------------
# Request Model
# --------------------------------------------------

class MessageRequest(BaseModel):
    room: str
    sender: str
    message: str


# --------------------------------------------------
# 공통 함수
# --------------------------------------------------

def format_event(event: Event) -> str:

    start = event.start_at.astimezone(KST)
    end = event.end_at.astimezone(KST)

    return (
        f"🎮 {event.title}\n"
        f"⏰ {start.strftime('%m/%d %H:%M')}"
        f" ~ {end.strftime('%H:%M')}"
    )


def get_events_between(start_dt, end_dt):

    with SessionLocal() as db:

        stmt = (
            select(Event)
            .where(Event.end_at >= start_dt)
            .where(Event.start_at < end_dt)
            .order_by(Event.start_at)
        )

        return db.scalars(stmt).all()


# --------------------------------------------------
# 기본 API
# --------------------------------------------------

@app.get("/")
def root():

    return {
        "name": "Pokemon GO Kakao Bot",
        "status": "running",
    }


@app.get("/health")
def health():

    return {
        "status": "ok",
    }


@app.get("/db-check")
def db_check():

    try:

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")

        return {
            "status": "ok",
            "database": "connected",
        }

    except Exception as e:

        return {
            "status": "error",
            "message": str(e),
        }


# --------------------------------------------------
# 테스트 이벤트 생성
# --------------------------------------------------

@app.post("/api/admin/seed-test")
def seed_test():

    now = datetime.now(KST)

    start = datetime.combine(
        now.date(),
        time(18, 0),
        tzinfo=KST,
    )

    end = datetime.combine(
        now.date(),
        time(19, 0),
        tzinfo=KST,
    )

    with SessionLocal() as db:

        event = Event(
            title="테스트 레이드아워",
            category="raid_hour",
            start_at=start,
            end_at=end,
            description="Pokémon GO 봇 테스트용 이벤트",
            source_name="TEST",
        )

        db.add(event)
        db.commit()
        db.refresh(event)

    return {
        "status": "ok",
        "event_id": event.id,
        "title": event.title,
    }


# --------------------------------------------------
# 이벤트 조회
# --------------------------------------------------

@app.get("/api/events/today")
def events_today():

    now = datetime.now(KST)

    start = datetime.combine(
        now.date(),
        time.min,
        tzinfo=KST,
    )

    end = start + timedelta(days=1)

    events = get_events_between(start, end)

    return {
        "count": len(events),
        "events": [
            {
                "id": event.id,
                "title": event.title,
                "category": event.category,
                "start_at": event.start_at,
                "end_at": event.end_at,
            }
            for event in events
        ],
    }


# --------------------------------------------------
# Kakao / MessengerBot API
# --------------------------------------------------

@app.post("/api/messages")
def receive_message(data: MessageRequest):

    msg = data.message.strip()

    # 서버 테스트
    if "포고봇 테스트" in msg:

        return {
            "reply": "✅ Pokémon GO 봇 서버 연결 정상입니다."
        }

    # 도움말
    if "포고봇 도움말" in msg:

        return {
            "reply": (
                "🤖 Pokémon GO 봇\n\n"
                "포고봇 오늘\n"
                "포고봇 내일\n"
                "포고봇 이번주\n"
                "포고봇 테스트"
            )
        }

    # 오늘
    if "포고봇 오늘" in msg:

        now = datetime.now(KST)

        start = datetime.combine(
            now.date(),
            time.min,
            tzinfo=KST,
        )

        end = start + timedelta(days=1)

        events = get_events_between(start, end)

        if not events:

            return {
                "reply": "📅 오늘 등록된 Pokémon GO 일정이 없습니다."
            }

        text = "📅 오늘의 Pokémon GO 일정\n\n"

        text += "\n\n".join(
            format_event(event)
            for event in events
        )

        return {
            "reply": text
        }

    # 내일
    if "포고봇 내일" in msg:

        now = datetime.now(KST)

        tomorrow = now.date() + timedelta(days=1)

        start = datetime.combine(
            tomorrow,
            time.min,
            tzinfo=KST,
        )

        end = start + timedelta(days=1)

        events = get_events_between(start, end)

        if not events:

            return {
                "reply": "📅 내일 등록된 Pokémon GO 일정이 없습니다."
            }

        text = "📅 내일의 Pokémon GO 일정\n\n"

        text += "\n\n".join(
            format_event(event)
            for event in events
        )

        return {
            "reply": text
        }

    # 이번주
    if "포고봇 이번주" in msg:

        now = datetime.now(KST)

        start = datetime.combine(
            now.date(),
            time.min,
            tzinfo=KST,
        )

        end = start + timedelta(days=7)

        events = get_events_between(start, end)

        if not events:

            return {
                "reply": "📅 앞으로 7일간 등록된 일정이 없습니다."
            }

        text = "📅 앞으로 7일간 Pokémon GO 일정\n\n"

        text += "\n\n".join(
            format_event(event)
            for event in events
        )

        return {
            "reply": text
        }

    return {
        "reply": None
    }
