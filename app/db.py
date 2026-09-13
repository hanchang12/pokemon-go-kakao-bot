import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pokemon_go_bot.db")

engine_options: dict = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}
if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
    engine_options["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


EVENT_COLUMN_MIGRATIONS = {
    "external_key": "VARCHAR(64)",
    "region": "VARCHAR(20) DEFAULT 'kr'",
    "pokemon": "JSON",
    "bonuses": "JSON",
    "confidence": "FLOAT",
    "verified": "BOOLEAN DEFAULT FALSE",
    "created_at": "TIMESTAMP WITH TIME ZONE",
    "updated_at": "TIMESTAMP WITH TIME ZONE",
    "last_checked_at": "TIMESTAMP WITH TIME ZONE",
}


def ensure_schema() -> None:
    """Create new tables and add non-destructive columns to an existing MVP DB."""
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "events" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("events")}
    with engine.begin() as connection:
        for name, sql_type in EVENT_COLUMN_MIGRATIONS.items():
            if name not in existing:
                connection.execute(text(f"ALTER TABLE events ADD COLUMN {name} {sql_type}"))
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "ix_events_external_key ON events (external_key)"
            )
        )
