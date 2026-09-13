import json
from types import SimpleNamespace

import pytest

from app import collector


VALID_EVENTS = {
    "events": [
        {
            "title": "테스트 이벤트",
            "category": "event",
            "start_at": "2026-09-14T10:00:00+09:00",
            "end_at": "2026-09-14T11:00:00+09:00",
            "description": "",
            "pokemon": [],
            "bonuses": [],
            "source_name": "Pokemon GO Live",
            "source_url": "https://pokemongolive.com/",
            "confidence": 1.0,
        }
    ]
}


class FakeChatCompletions:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content=next(self.contents))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_client(contents):
    completions = FakeChatCompletions(contents)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_groq_collection_uses_web_search_and_validates_json(monkeypatch):
    client, completions = fake_client([json.dumps(VALID_EVENTS)])
    created_with = {}

    def openai_factory(**kwargs):
        created_with.update(kwargs)
        return client

    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(collector, "OpenAI", openai_factory)

    result = collector._collect_with_groq("find events")

    assert result.events[0].title == "테스트 이벤트"
    assert created_with == {
        "api_key": "test-groq-key",
        "base_url": "https://api.groq.com/openai/v1",
    }
    request = completions.calls[0]
    assert request["model"] == "groq/compound"
    assert request["response_format"] == {"type": "json_object"}
    assert request["extra_body"]["search_settings"] == {
        "include_domains": ["pokemongolive.com", "leekduck.com"],
        "country": "south korea",
    }


def test_groq_collection_retries_invalid_schema(monkeypatch):
    client, completions = fake_client(
        [json.dumps({"events": [{"title": "missing fields"}]}), json.dumps(VALID_EVENTS)]
    )
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setattr(collector, "OpenAI", lambda **kwargs: client)

    result = collector._collect_with_groq("find events")

    assert result.events[0].title == "테스트 이벤트"
    assert len(completions.calls) == 2
    assert "did not match" in completions.calls[1]["messages"][-1]["content"]


def test_provider_configuration_defaults_to_groq(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert collector._provider_name() == "groq"
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        collector._require_provider_key("groq")


def test_unknown_provider_is_rejected():
    with pytest.raises(RuntimeError, match="AI_PROVIDER"):
        collector._require_provider_key("unknown")
