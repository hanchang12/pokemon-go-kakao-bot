import os

from fastapi import FastAPI
from sqlalchemy import create_engine, text

app = FastAPI(
    title="Pokemon GO Kakao Bot",
    version="0.2.0"
)

DATABASE_URL = os.getenv("DATABASE_URL")


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
