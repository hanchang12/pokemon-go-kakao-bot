from sqlalchemy import inspect, text

from app.db import Base, engine, ensure_schema


def test_legacy_events_table_is_upgraded_without_deleting_rows():
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY,
                    title VARCHAR(200) NOT NULL,
                    category VARCHAR(50) NOT NULL,
                    start_at TIMESTAMP NOT NULL,
                    end_at TIMESTAMP NOT NULL,
                    description TEXT,
                    source_name VARCHAR(100),
                    source_url TEXT
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO events
                    (id, title, category, start_at, end_at)
                VALUES
                    (1, 'legacy event', 'event', '2026-09-13 10:00:00', '2026-09-13 11:00:00')
                """
            )
        )

    ensure_schema()

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("events")}
    assert {"external_key", "pokemon", "bonuses", "last_checked_at"} <= columns
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM events")) == 1


def test_legacy_subscriptions_table_gains_kind_column_and_allows_multiple_per_room():
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE subscriptions (
                    id INTEGER PRIMARY KEY,
                    room VARCHAR(200) NOT NULL,
                    recurring BOOLEAN NOT NULL,
                    send_time VARCHAR(5) NOT NULL,
                    next_fire_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO subscriptions
                    (id, room, recurring, send_time, next_fire_at, created_at)
                VALUES
                    (1, '테스트방', 1, '09:00', '2026-09-14 09:00:00', '2026-09-13 00:00:00')
                """
            )
        )

    ensure_schema()

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("subscriptions")}
    assert "kind" in columns
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT kind FROM subscriptions WHERE id = 1")) == "digest"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO subscriptions
                    (room, kind, recurring, send_time, next_fire_at, created_at)
                VALUES
                    ('테스트방', 'raid_hour', 1, '17:50', '2026-09-16 17:50:00', '2026-09-13 00:00:00')
                """
            )
        )
    with engine.connect() as connection:
        count = connection.scalar(text("SELECT COUNT(*) FROM subscriptions WHERE room = '테스트방'"))
        assert count == 2
