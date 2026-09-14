import json

from app import tier_source
from app.tier_source import parse_tier_list, translate_pokemon_names_to_korean

SAMPLE_HTML = """
<html><body>
<div><h2>Bug Type</h2></div>
<p>One of the weakest types in Pokemon Go, low priority overall for raids.</p>
<div>Mega Heracross</div>
<div>Shadow Vikavolt</div>
<div>Mega Pinsir</div>
<div><h2>Dark Type</h2></div>
<p>Dark Type has the advantage of dealing Super Effective damage widely.</p>
<div>Mega Absol</div>
<div>Mega Tyranitar</div>
<p>Log in</p>
<p>to comment.</p>
<div>이 밑은 댓글이라 무시돼야 한다</div>
</body></html>
"""


def test_parse_tier_list_splits_by_type_and_maps_korean_names():
    result = parse_tier_list(SAMPLE_HTML)

    assert result["벌레"] == ["Mega Heracross", "Shadow Vikavolt", "Mega Pinsir"]
    assert result["악"] == ["Mega Absol", "Mega Tyranitar"]


def test_parse_tier_list_stops_before_comments():
    result = parse_tier_list(SAMPLE_HTML)
    assert "댓글" not in " ".join(result["악"])


def test_parse_tier_list_raises_without_recognizable_type_headers():
    try:
        parse_tier_list("<html><body><p>no types here</p></body></html>")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakePokeApiClient:
    def __init__(self, species_names):
        self.species_names = species_names
        self.requested_urls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        self.requested_urls.append(url)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        if slug not in self.species_names:
            return FakeResponse({"names": []})
        return FakeResponse(
            {"names": [{"language": {"name": "ko"}, "name": self.species_names[slug]}]}
        )


def test_translate_pokemon_names_handles_mega_xy_forms(monkeypatch):
    # "Mega Charizard Y" -> 접두어(Mega)와 끝의 단일 알파벳(Y)을 떼고 남는
    # "Charizard"만 PokeAPI 종 이름으로 조회한 뒤, 떼어둔 조각을 다시 붙인다.
    fake = FakePokeApiClient({"charizard": "리자몽"})
    monkeypatch.setattr(tier_source.httpx, "Client", lambda **kwargs: fake)

    result = translate_pokemon_names_to_korean(["Mega Charizard Y"])

    assert fake.requested_urls == ["https://pokeapi.co/api/v2/pokemon-species/charizard/"]
    assert result == {"Mega Charizard Y": "메가 리자몽 Y"}


def test_translate_pokemon_names_applies_known_prefix_and_species_lookup(monkeypatch):
    fake = FakePokeApiClient({"kyogre": "가이오가"})
    monkeypatch.setattr(tier_source.httpx, "Client", lambda **kwargs: fake)

    result = translate_pokemon_names_to_korean(["Shadow Kyogre"])

    assert result == {"Shadow Kyogre": "섀도 가이오가"}


def test_translate_pokemon_names_keeps_form_suffix_untranslated(monkeypatch):
    fake = FakePokeApiClient({"landorus": "랜드로스"})
    monkeypatch.setattr(tier_source.httpx, "Client", lambda **kwargs: fake)

    result = translate_pokemon_names_to_korean(["Landorus (Therian Forme)"])

    assert result == {"Landorus (Therian Forme)": "랜드로스 (Therian Forme)"}


def test_translate_pokemon_names_skips_names_pokeapi_does_not_know(monkeypatch):
    fake = FakePokeApiClient({})
    monkeypatch.setattr(tier_source.httpx, "Client", lambda **kwargs: fake)

    result = translate_pokemon_names_to_korean(["Totally Unknown Pokemon"])

    assert result == {}
