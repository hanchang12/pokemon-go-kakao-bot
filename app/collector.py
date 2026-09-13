import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.event_service import upsert_event
from app.korean_source import fetch_korean_records
from app.models import CollectRun, utc_now
from app.schemas import CollectedEvents
from app.source_fetcher import fetch_event_candidates


KST = ZoneInfo("Asia/Seoul")
LOGGER = logging.getLogger(__name__)
ALLOWED_DOMAINS = ["pokemongo.com", "pokemongolive.com", "leekduck.com"]

# 공식 한국 사이트에 실리지 않는 주간 반복 일정을 Leek Duck에서 채울 때 쓰는 표기 사전.
KOREAN_GLOSSARY = """
Raid Hour -> 레이드아워 (매주 수요일 18:00~19:00)
Pokemon Spotlight Hour -> 스포트라이트아워 (매주 목요일 18:00~19:00)
Max Monday -> 맥스먼데이 (매주 월요일)
Mega Raids -> 메가 레이드
5-star Raid Battles -> 별5 레이드배틀
Shadow Raids -> 그림자 레이드
GO Battle League -> GO배틀리그
Community Day -> 커뮤니티 데이
Community Day Classic -> 커뮤니티 데이(복각)
Raid Day / Super Mega Raid Day -> 레이드 데이 / 슈퍼 메가 레이드 데이
Max Battle Day -> 맥스배틀 데이
Hatch Day -> 부화데이
Catch Mastery / Mastery Series -> 마스터리 시리즈
GO Pass -> GO패스
Season -> 시즌
""".strip()
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

Convert the source records below into the requested event schema.

Source priority:
1. "공식 한국 뉴스" blocks are the official Korean site and outrank everything else.
   Their bodies state schedules as "한국시간 2026년 9월 29일 10:00부터 10월 5일 20:00까지";
   read those literally as Asia/Seoul times. One article may describe several events
   (for example 파트1~파트4) - emit each dated schedule as its own event.
2. "Leek Duck 보조 일정" blocks only fill in what the official Korean site never
   publishes: 레이드아워, 스포트라이트아워, 맥스먼데이 and the weekly raid boss and
   GO배틀리그 rotations. Their timestamps already carry a +09:00 offset - copy them.

Titles must be Korean. When an event appears in a 공식 한국 뉴스 block, reuse that
article's exact Korean wording, including the official Korean Pokemon names. For an
event that exists only in a Leek Duck block, translate it with this glossary and use
official Korean Pokemon names:
{KOREAN_GLOSSARY}

Set region for every event:
- "kr" when players in Korea can take part. Worldwide events that run at local time
  (레이드아워, 스포트라이트아워, 맥스먼데이, 커뮤니티 데이, raid rotations) are "kr".
- "overseas" only for in-person or ticketed events held outside Korea, such as
  "Pokemon GO 와일드 에리어: 센다이, 도호쿠" or a GO Fest city stop abroad.
  An in-person event held in Korea stays "kr".

If the same event appears in both sources, emit it once, using the Korean title and
the official pokemongo.com URL. Use only facts and source URLs present in the
records; never invent dates, times, bonuses, Pokemon, or URLs. Return an empty
events array when nothing matches. Use confidence 0.9 for events taken from 공식
한국 뉴스 and 0.75 for events taken only from Leek Duck.

Source records:
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


def build_source_text(now: datetime, until: datetime) -> str:
    """공식 한국 뉴스를 앞에, Leek Duck 보조 일정을 뒤에 붙인 소스 텍스트."""
    korean = fetch_korean_records(now)
    sections = [f"## 공식 한국 뉴스 (pokemongo.com/ko) - 1순위\n\n{korean}"]
    try:
        leekduck = fetch_event_candidates(now, until)
    except Exception as exc:  # 보조 소스는 실패해도 수집을 막지 않는다
        LOGGER.warning("Leek Duck 보조 소스를 건너뜁니다: %s", exc)
    else:
        sections.append(
            "## Leek Duck 보조 일정 (leekduck.com) - 공식 한국 사이트에 없는 "
            f"주간 반복 일정 보완용\n\n{leekduck}"
        )
    return "\n\n".join(sections)


def _collect_from_provider(provider: str, prompt: str) -> CollectedEvents:
    if provider == "gemini":
        now = datetime.now(KST)
        until = now + timedelta(days=60)
        return _collect_with_gemini(prompt, build_source_text(now, until))
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
Collect confirmed Pokemon GO events that are running or begin between
{now.isoformat()} and {until.isoformat()}, written for players in South Korea.

The official Korean site pokemongo.com/ko is the primary source; Leek Duck is
secondary and only covers what the official Korean site never publishes. Return
each distinct event once, with a Korean title. Express start_at and end_at in
Asia/Seoul with an explicit UTC offset. Do not invent dates, bonuses, Pokemon, or
URLs. Exclude unconfirmed rumors and events that end before this window starts.
Choose the closest category from the supplied schema, and set region to "kr" for
anything playable in Korea or "overseas" for in-person events held abroad.
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
