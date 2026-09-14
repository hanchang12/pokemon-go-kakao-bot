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

    if "events" in inspector.get_table_names():
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

    if "subscriptions" in inspector.get_table_names():
        sub_columns = {column["name"] for column in inspector.get_columns("subscriptions")}
        with engine.begin() as connection:
            if "kind" not in sub_columns:
                connection.execute(
                    text("ALTER TABLE subscriptions ADD COLUMN kind VARCHAR(20) DEFAULT 'digest'")
                )
                connection.execute(text("UPDATE subscriptions SET kind = 'digest' WHERE kind IS NULL"))
            if engine.dialect.name == "postgresql":
                # 예전 스키마는 room 단독 UNIQUE였다 - 방 하나에 종류(kind)별로
                # 여러 예약을 두려면 그 단일 컬럼 제약을 걷어내야 한다. 제약
                # 이름은 SQLAlchemy가 자동 생성해 고정돼 있지 않으니 카탈로그에서 찾는다.
                constraint_names = connection.execute(
                    text(
                        """
                        SELECT tc.constraint_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.constraint_column_usage ccu
                          ON tc.constraint_name = ccu.constraint_name
                         AND tc.table_schema = ccu.table_schema
                        WHERE tc.table_name = 'subscriptions'
                          AND tc.constraint_type = 'UNIQUE'
                          AND ccu.column_name = 'room'
                        """
                    )
                ).scalars().all()
                for name in constraint_names:
                    connection.execute(text(f'ALTER TABLE subscriptions DROP CONSTRAINT "{name}"'))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ix_subscriptions_room_kind ON subscriptions (room, kind)"
                )
            )
