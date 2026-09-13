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
