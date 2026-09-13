import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from openai import OpenAI
from sqlalchemy.orm import Session

from app.event_service import upsert_event
from app.models import CollectRun, utc_now
from app.schemas import CollectedEvents


KST = ZoneInfo("Asia/Seoul")
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
ALLOWED_DOMAINS = ["pokemongolive.com", "leekduck.com"]


def collect_events(db: Session, days: int = 30) -> CollectRun:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not 1 <= days <= 60:
        raise ValueError("days must be between 1 and 60")

    run = CollectRun(status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    now = datetime.now(KST)
    until = now + timedelta(days=days)
    client = OpenAI()
    prompt = f"""
Search for confirmed Pokemon GO events that are active or begin between
{now.isoformat()} and {until.isoformat()} for players in South Korea.

Use official Pokemon GO pages as the primary source and Leek Duck only as a
secondary source. Return each distinct event once. Convert local-time events to
Asia/Seoul and include an explicit UTC offset in start_at and end_at. Do not
invent dates, bonuses, Pokemon, or URLs. Exclude unconfirmed rumors and events
whose end time is before the start of this collection window. Choose the closest
category from the supplied schema. Confidence should reflect source quality and
date certainty; official confirmed schedules should normally be at least 0.8.
""".strip()

    try:
        response = client.responses.parse(
            model=MODEL,
            tools=[
                {
                    "type": "web_search",
                    "filters": {"allowed_domains": ALLOWED_DOMAINS},
                    "user_location": {
                        "type": "approximate",
                        "country": "KR",
                        "city": "Seoul",
                        "region": "Seoul",
                    },
                }
            ],
            input=prompt,
            text_format=CollectedEvents,
        )
        result = response.output_parsed
        if result is None:
            raise RuntimeError("OpenAI returned no structured event data")

        inserted = 0
        updated = 0
        for item in result.events:
            _, created = upsert_event(db, item)
            inserted += int(created)
            updated += int(not created)

        run.status = "completed"
        run.finished_at = utc_now()
        run.found_count = len(result.events)
        run.inserted_count = inserted
        run.updated_count = updated
        db.commit()
        db.refresh(run)
        return run
    except Exception as exc:
        db.rollback()
        run = db.get(CollectRun, run.id)
        if run is not None:
            run.status = "failed"
            run.finished_at = utc_now()
            run.error_message = str(exc)[:2000]
            db.commit()
        raise
