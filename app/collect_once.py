from app.collector import collect_events
from app.db import SessionLocal, ensure_schema


def main() -> None:
    ensure_schema()
    with SessionLocal() as db:
        run = collect_events(db, days=30)
        print(
            f"collection completed: found={run.found_count} "
            f"inserted={run.inserted_count} updated={run.updated_count}"
        )


if __name__ == "__main__":
    main()
