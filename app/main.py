import os

from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy import create_engine, text

app = FastAPI(
    title="Pokemon GO Kakao Bot",
    version="0.3.0"
)

DATABASE_URL = os.getenv("DATABASE_URL")


class MessageRequest(BaseModel):
    room: str
    sender: str
    message: str


@app.get("/")
def root():
    return {
        "name": "Pokemon GO Kakao Bot",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


@app.get("/db-check")
def db_check():
    if not DATABASE_URL:
        return {
            "status": "error",
            "message": "DATABASE_URL is not configured"
        }

    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True
        )

        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1")
            ).scalar()

        return {
            "status": "ok",
            "database": "connected",
            "result": result
        }

    except Exception as e:
        return {
            "status": "error",
            "database": "connection_failed",
            "message": str(e)
        }


@app.post("/api/messages")
def receive_message(data: MessageRequest):

    msg = data.message.strip()

    if "포고봇 테스트" in msg:
        return {
            "reply": "✅ Pokémon GO 봇 서버 연결 정상입니다."
        }

    if "포고봇 도움말" in msg:
        return {
            "reply": (
                "🤖 Pokémon GO 봇 도움말\n\n"
                "포고봇 테스트\n"
                "포고봇 오늘\n"
                "포고봇 내일\n"
                "포고봇 이번주\n"
                "포고봇 레이드\n"
                "포고봇 커뮤"
            )
        }

    return {
        "reply": None
    }
