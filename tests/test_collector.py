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


class FakeGeminiModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            text=json.dumps(VALID_EVENTS),
            parsed=collector.CollectedEvents.model_validate(VALID_EVENTS),
        )


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
        "include_domains": [
            "pokemongo.com",
            "pokemongolive.com",
            "poketory.com",
            "pgsharp-info.com",
        ],
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


def test_nvidia_collection_uses_openai_compatible_endpoint(monkeypatch):
    client, completions = fake_client([json.dumps(VALID_EVENTS)])
    created_with = {}

    def openai_factory(**kwargs):
        created_with.update(kwargs)
        return client

    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setattr(collector, "OpenAI", openai_factory)

    result = collector._collect_with_nvidia("find events", "source records")

    assert result.events[0].title == "테스트 이벤트"
    assert created_with["api_key"] == "test-nvidia-key"
    assert created_with["base_url"] == "https://integrate.api.nvidia.com/v1"
    request = completions.calls[0]
    assert request["model"] == "google/gemma-4-31b-it"
    assert request["response_format"] == {"type": "json_object"}
    assert "source records" in request["messages"][-1]["content"]


def test_nvidia_collection_retries_invalid_schema(monkeypatch):
    client, completions = fake_client(
        [json.dumps({"events": [{"title": "missing fields"}]}), json.dumps(VALID_EVENTS)]
    )
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setattr(collector, "OpenAI", lambda **kwargs: client)

    result = collector._collect_with_nvidia("find events", "source records")

    assert result.events[0].title == "테스트 이벤트"
    assert len(completions.calls) == 2


def test_nvidia_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        collector._require_provider_key("nvidia")


def test_gemini_collection_searches_then_structures(monkeypatch):
    models = FakeGeminiModels()
    client = SimpleNamespace(models=models)
    created_with = {}

    def client_factory(**kwargs):
        created_with.update(kwargs)
        return client

    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setattr(collector.genai, "Client", client_factory)

    result = collector._collect_with_gemini("find events", "public source records")

    assert result.events[0].title == "테스트 이벤트"
    assert created_with == {"api_key": "test-gemini-key"}
    assert len(models.calls) == 1
    assert models.calls[0]["model"] == "gemini-3.6-flash"
    structure_config = models.calls[0]["config"]
    assert structure_config.response_mime_type == "application/json"
    assert structure_config.response_schema is collector.CollectedEvents


def test_deprecated_gemini_model_is_upgraded(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

    assert collector._gemini_model() == "gemini-3.6-flash"


def test_provider_configuration_defaults_to_gemini(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    assert collector._provider_name() == "gemini"
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        collector._require_provider_key("gemini")


def test_unknown_provider_is_rejected():
    with pytest.raises(RuntimeError, match="AI_PROVIDER"):
        collector._require_provider_key("unknown")


def test_translate_pokemon_names_matches_by_json_key(monkeypatch):
    payload = json.dumps({"Mega Charizard Y": "메가리자몽Y", "Shadow Kyogre": "섀도 가이오가"})
    client, completions = fake_client([payload])
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setattr(collector, "OpenAI", lambda **kwargs: client)

    result = collector.translate_pokemon_names_to_korean(
        ["Mega Charizard Y", "Shadow Kyogre"]
    )

    assert result == {
        "Mega Charizard Y": "메가리자몽Y",
        "Shadow Kyogre": "섀도 가이오가",
    }
    assert "Mega Charizard Y" in completions.calls[0]["messages"][-1]["content"]
    assert completions.calls[0]["response_format"] == {"type": "json_object"}


def test_translate_pokemon_names_ignores_hallucinated_keys(monkeypatch):
    payload = json.dumps({"Mega Charizard Y": "메가리자몽Y", "Not Requested": "존재안함"})
    client, _ = fake_client([payload])
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setattr(collector, "OpenAI", lambda **kwargs: client)

    result = collector.translate_pokemon_names_to_korean(["Mega Charizard Y"])

    assert result == {"Mega Charizard Y": "메가리자몽Y"}


def test_translate_pokemon_names_missing_entry_omitted(monkeypatch):
    payload = json.dumps({"Mega Charizard Y": "메가리자몽Y"})
    client, _ = fake_client([payload])
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setattr(collector, "OpenAI", lambda **kwargs: client)

    result = collector.translate_pokemon_names_to_korean(["Mega Charizard Y", "Unmapped"])

    assert result == {"Mega Charizard Y": "메가리자몽Y"}


def test_translate_pokemon_names_batches_large_lists(monkeypatch):
    names = [f"Pokemon{i}" for i in range(30)]
    batch1 = {name: f"번역{i}" for i, name in enumerate(names[:25])}
    batch2 = {name: f"번역{i + 25}" for i, name in enumerate(names[25:])}
    client, completions = fake_client([json.dumps(batch1), json.dumps(batch2)])
    monkeypatch.setenv("NVIDIA_API_KEY", "test-nvidia-key")
    monkeypatch.setattr(collector, "OpenAI", lambda **kwargs: client)

    result = collector.translate_pokemon_names_to_korean(names)

    assert len(completions.calls) == 2
    assert len(result) == 30
    assert result["Pokemon0"] == "번역0"
    assert result["Pokemon29"] == "번역29"


def test_translate_pokemon_names_empty_input_skips_api_call(monkeypatch):
    def fail_factory(**kwargs):
        raise AssertionError("should not call OpenAI for empty input")

    monkeypatch.setattr(collector, "OpenAI", fail_factory)

    assert collector.translate_pokemon_names_to_korean([]) == {}
