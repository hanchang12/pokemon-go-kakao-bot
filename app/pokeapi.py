"""PokeAPI(pokeapi.co) 공용 헬퍼 - 종(species) 한국어 이름 조회, 진화 체인 조회.

무료 공식 다국어 포켓몬 데이터베이스. AI 번역과 달리 실제 정발 명칭을 그대로
제공해서 틀릴 일이 없다 (app/tier_source.py에서 AI 번역을 이걸로 교체한 이유).
"""

import httpx


USER_AGENT = "pokemon-go-kakao-bot/1.0"
POKEAPI_SPECIES_URL = "https://pokeapi.co/api/v2/pokemon-species/{slug}/"


def pokeapi_korean_species_name(client: httpx.Client, base_name: str) -> str | None:
    slug = base_name.lower().replace(" ", "-").replace("'", "").replace(".", "")
    try:
        response = client.get(POKEAPI_SPECIES_URL.format(slug=slug))
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    for entry in response.json().get("names", []):
        if entry["language"]["name"] == "ko":
            return entry["name"]
    return None


def fetch_evolution_chain_korean(species_name: str) -> list[list[str]] | None:
    """영문 종 이름으로 진화 체인을 찾아 단계별 한국어 이름 리스트로 반환한다.

    이브이처럼 갈라지는 경우 같은 단계에 여러 이름이 들어간다. 이름을 못
    찾으면 None. 체인 길이가 보통 1~3단계(이브이 계열만 예외)라 채팅
    응답 시간 안에 동기로 끝난다 - NVIDIA와 달리 PokeAPI는 느리지 않다.
    """
    slug = species_name.strip().lower().replace(" ", "-")
    with httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        try:
            species_response = client.get(POKEAPI_SPECIES_URL.format(slug=slug))
            species_response.raise_for_status()
        except httpx.HTTPError:
            return None

        chain_url = species_response.json()["evolution_chain"]["url"]
        try:
            chain_response = client.get(chain_url)
            chain_response.raise_for_status()
        except httpx.HTTPError:
            return None

        stages: list[list[str]] = []

        def walk(node: dict, depth: int) -> None:
            name_en = node["species"]["name"]
            name_ko = pokeapi_korean_species_name(client, name_en) or name_en
            if len(stages) <= depth:
                stages.append([])
            stages[depth].append(name_ko)
            for child in node["evolves_to"]:
                walk(child, depth + 1)

        walk(chain_response.json()["chain"], 0)

    return stages
