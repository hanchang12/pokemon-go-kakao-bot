import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.event_service import upsert_event
from app.models import CollectRun, utc_now
from app.schemas import CollectedEvents
from app.source_fetcher import fetch_event_candidates


KST = ZoneInfo("Asia/Seoul")
ALLOWED_DOMAINS = ["pokemongolive.com", "leekduck.com"]
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _provider_name() -> str:
    return os.getenv("AI_PROVIDER", "gemini").strip().lower()


def _require_provider_key(provider: str) -> None:
    if provider == "gemini" and not os.getenv("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not configured")
    if provider == "groq" and not os.getenv("GROQ_API_KEY"):
        raise RuntimeError("GROQ_API_KEY is not configured")
    if provider == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if provider not in {"gemini", "groq", "openai"}:
        raise RuntimeError("AI_PROVIDER must be 'gemini', 'groq', or 'openai'")


def _gemini_model() -> str:
    configured = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
    if configured in {"gemini-2.5-flash", "models/gemini-2.5-flash"}:
        return "gemini-3.6-flash"
    return configured


def _collect_with_gemini(prompt: str, source_text: str) -> CollectedEvents:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    structure_prompt = f"""
{prompt}

Convert the public schedule records below into the requested event schema.

Use only facts and source URLs present in the records. Do not invent missing
dates, times, bonuses, Pokemon, or URLs. Return an empty events array when the
records contain no confirmed matching events. Preserve the supplied timestamps
and URLs exactly. Map each source type to the closest category in the schema.
Use confidence 0.75 because Leek Duck is a secondary source.

Public schedule records:
{source_text}
""".strip()
    structured = client.models.generate_content(
        model=_gemini_model(),
        contents=structure_prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=CollectedEvents,
            temperature=0.1,
        ),
    )
    if isinstance(structured.parsed, CollectedEvents):
        return structured.parsed
    if structured.parsed is not None:
        return CollectedEvents.model_validate(structured.parsed)
    if not structured.text:
        raise RuntimeError("Gemini returned no structured event data")
    return CollectedEvents.model_validate_json(structured.text)


def _collect_with_groq(prompt: str) -> CollectedEvents:
    client = OpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url=GROQ_BASE_URL,
    )
    schema = json.dumps(
        CollectedEvents.model_json_schema(), ensure_ascii=False, separators=(",", ":")
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a web research API. Use web search and website visits. "
                "Respond with one JSON object only, without markdown or citations "
                "outside JSON. The JSON must match the supplied schema exactly."
            ),
        },
        {
            "role": "user",
            "content": f"{prompt}\n\nRequired JSON Schema:\n{schema}",
        },
    ]
    last_error: ValidationError | None = None

    for attempt in range(2):
        response = client.chat.completions.create(
            model=os.getenv("GROQ_MODEL", "groq/compound"),
            messages=messages,
            response_format={"type": "json_object"},
            extra_body={
                "search_settings": {
                    "include_domains": ALLOWED_DOMAINS,
                    "country": "south korea",
                }
            },
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("Groq returned no event data")
        try:
            return CollectedEvents.model_validate_json(content)
        except ValidationError as exc:
            last_error = exc
            if attempt == 0:
                messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "The previous JSON did not match the required schema. "
                                f"Correct it and return JSON only. Validation error: {exc}"
                            ),
                        },
                    ]
                )

    raise RuntimeError(f"Groq returned invalid event data: {last_error}")


def _collect_with_openai(prompt: str) -> CollectedEvents:
    client = OpenAI()
    response = client.responses.parse(
        model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
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
    if response.output_parsed is None:
        raise RuntimeError("OpenAI returned no structured event data")
    return response.output_parsed


def _collect_from_provider(provider: str, prompt: str) -> CollectedEvents:
    if provider == "gemini":
        now = datetime.now(KST)
        until = now + timedelta(days=60)
        return _collect_with_gemini(prompt, fetch_event_candidates(now, until))
    if provider == "groq":
        return _collect_with_groq(prompt)
    return _collect_with_openai(prompt)


def collect_events(db: Session, days: int = 30) -> CollectRun:
    provider = _provider_name()
    _require_provider_key(provider)
    if not 1 <= days <= 60:
        raise ValueError("days must be between 1 and 60")

    run = CollectRun(status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    now = datetime.now(KST)
    until = now + timedelta(days=days)
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
        result = _collect_from_provider(provider, prompt)

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
