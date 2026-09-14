from app import pokeapi
from app.pokeapi import fetch_evolution_chain_korean


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


KOREAN_NAMES = {
    "charmander": "파이리",
    "charmeleon": "리자드",
    "charizard": "리자몽",
    "eevee": "이브이",
    "vaporeon": "샤미드",
    "jolteon": "쥬피썬더",
}


class FakeEvolutionClient:
    """species -> evolution_chain URL -> chain tree, plus per-species 이름 조회."""

    def __init__(self, species_slug, chain):
        self.species_slug = species_slug
        self.chain = chain

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get(self, url):
        if url == "https://pokeapi.co/api/v2/evolution-chain/1/":
            return FakeResponse({"chain": self.chain})
        # 실제 PokeAPI의 species 응답엔 evolution_chain과 names가 같이 들어있다 -
        # 루트 노드는 진화체인 URL 조회와 이름 조회가 같은 URL을 두 번 친다.
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        payload = {"evolution_chain": {"url": "https://pokeapi.co/api/v2/evolution-chain/1/"}}
        if slug in KOREAN_NAMES:
            payload["names"] = [{"language": {"name": "ko"}, "name": KOREAN_NAMES[slug]}]
        else:
            payload["names"] = []
        return FakeResponse(payload)


def _node(name, children=None):
    return {"species": {"name": name}, "evolves_to": children or []}


def test_fetch_evolution_chain_linear(monkeypatch):
    chain = _node("charmander", [_node("charmeleon", [_node("charizard")])])
    fake = FakeEvolutionClient("charmander", chain)
    monkeypatch.setattr(pokeapi.httpx, "Client", lambda **kwargs: fake)

    result = fetch_evolution_chain_korean("charmander")

    assert result == [["파이리"], ["리자드"], ["리자몽"]]


def test_fetch_evolution_chain_branching(monkeypatch):
    chain = _node("eevee", [_node("vaporeon"), _node("jolteon")])
    fake = FakeEvolutionClient("eevee", chain)
    monkeypatch.setattr(pokeapi.httpx, "Client", lambda **kwargs: fake)

    result = fetch_evolution_chain_korean("eevee")

    assert result == [["이브이"], ["샤미드", "쥬피썬더"]]


def test_fetch_evolution_chain_unknown_species_returns_none(monkeypatch):
    class FailingClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            import httpx

            raise httpx.HTTPStatusError("not found", request=None, response=None)

    monkeypatch.setattr(pokeapi.httpx, "Client", lambda **kwargs: FailingClient())

    assert fetch_evolution_chain_korean("nosuchpokemon") is None


def test_fetch_evolution_chain_falls_back_to_english_when_unknown_ko_name(monkeypatch):
    chain = _node("missingno")
    fake = FakeEvolutionClient("missingno", chain)
    monkeypatch.setattr(pokeapi.httpx, "Client", lambda **kwargs: fake)

    result = fetch_evolution_chain_korean("missingno")

    assert result == [["missingno"]]
