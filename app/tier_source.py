"""외부 티어리스트 사이트(PokéBase)에서 타입별 상위 공격 포켓몬 목록을 가져온다.

정적 데이터인 타입 상성(app/type_chart.py)과 달리 이건 게임 밸런스 패치·신규
포켓몬 출시로 바뀌는 정보라, 매번 수집하지 않고 한 달에 한 번만 갱신한다
(app/scheduler.py에서 마지막 갱신일을 체크).
"""

import re

import httpx

from app.korean_source import ArticleTextParser
from app.pokeapi import USER_AGENT, pokeapi_korean_species_name


TIER_LIST_URL = "https://pokebase.app/pokemon-go/p/best-attackers-by-type"

# 소스 사이트(영문) 타입 헤더 -> 한국어 타입명 (app.type_chart.ALL_TYPES와 동일 집합)
EN_TO_KO_TYPE = {
    "Bug": "벌레", "Dark": "악", "Dragon": "드래곤", "Electric": "전기",
    "Fairy": "페어리", "Fighting": "격투", "Fire": "불꽃", "Flying": "비행",
    "Ghost": "고스트", "Grass": "풀", "Ground": "땅", "Ice": "얼음",
    "Normal": "노말", "Poison": "독", "Psychic": "에스퍼", "Rock": "바위",
    "Steel": "강철", "Water": "물",
}

TYPE_HEADER_PATTERN = re.compile(r"^(" + "|".join(EN_TO_KO_TYPE) + r") Type$", re.MULTILINE)
STOP_MARKER = "Log in"  # 이 뒤로는 댓글란
MAX_POKEMON_PER_TYPE = 12


def fetch_tier_list() -> dict[str, list[str]]:
    """{한국어 타입명: [포켓몬 이름(영문), ...]} - 사이트가 매긴 순위 순서 그대로."""
    with httpx.Client(
        follow_redirects=True, timeout=20, headers={"User-Agent": USER_AGENT}
    ) as client:
        response = client.get(TIER_LIST_URL)
        response.raise_for_status()
        html = response.text

    return parse_tier_list(html)


def parse_tier_list(html: str) -> dict[str, list[str]]:
    parser = ArticleTextParser()
    parser.feed(html)
    text = parser.text()
    cut_at = text.find(STOP_MARKER)
    if cut_at != -1:
        text = text[:cut_at]

    matches = list(TYPE_HEADER_PATTERN.finditer(text))
    if not matches:
        raise RuntimeError("티어리스트 페이지에서 타입 구간을 찾지 못했습니다")

    result: dict[str, list[str]] = {}
    for i, match in enumerate(matches):
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[match.end():section_end]
        # 설명 문단은 길고 마침표로 끝나는 한 줄, 포켓몬 이름은 짧은 줄이라 길이로 가른다
        names = [
            line.strip()
            for line in section.split("\n")
            if line.strip() and len(line.strip()) < 40 and not line.strip().endswith(".")
        ]
        result[EN_TO_KO_TYPE[match.group(1)]] = names[:MAX_POKEMON_PER_TYPE]
    return result


# Mega/Shadow 등 접두어와 지역폼은 기계적으로 번역한다 - 이건 항상 같은 규칙이라
# 틀릴 일이 없다. 불확실한 건 기본 종 이름뿐이라 그것만 PokeAPI에서 조회한다.
PREFIX_TRANSLATIONS = [
    ("Mega ", "메가 "),
    ("Shadow ", "섀도 "),
    ("Primal ", "프라이멀 "),
    ("Dynamax ", "다이맥스 "),
    ("Gigantamax ", "거다이맥스 "),
    ("Galarian ", "가라르 "),
    ("Alolan ", "알로라 "),
    ("Hisuian ", "히스이 "),
    ("Paldean ", "팔데아 "),
]

# "Zacian - Crowned Sword", "Landorus (Therian Forme)" 같은 폼 설명은 번역하지
# 않고 영문 그대로 뒤에 남긴다 - 번역 시도하다 다른 포켓몬 이름을 지어내는 것보단
# 낫다. "Mega Charizard X/Y"처럼 끝의 단일 알파벳(X/Y)은 한국에서도 그대로
# "X"/"Y"로 쓰므로 같은 방식으로 떼어뒀다가 그대로 붙인다.
FORM_SUFFIX_PATTERN = re.compile(r"^(.*?)\s*(\(.+\)|-\s+.+|\s[XY])$")


def _strip_known_prefix(name: str) -> tuple[str, str]:
    for en_prefix, ko_prefix in PREFIX_TRANSLATIONS:
        if name.startswith(en_prefix):
            return ko_prefix, name[len(en_prefix):]
    return "", name


def _split_form_suffix(name: str) -> tuple[str, str]:
    match = FORM_SUFFIX_PATTERN.match(name)
    if match:
        return match.group(1).strip(), " " + match.group(2).strip()
    return name.strip(), ""


def translate_pokemon_names_to_korean(names: list[str]) -> dict[str, str]:
    """영문 포켓몬 이름을 한국 공식 명칭으로 번역한다.

    처음엔 NVIDIA(AI)로 번역을 시켰는데, 한국 정발명이 음역이 아니라 완전히
    다른 창작명인 경우가 많아서(예: Blastoise -> "블라스터"가 아니라 "거북왕")
    모델이 그럴듯하지만 틀린 이름을 지어내는 사고가 실제로 있었다(Shadow
    Kyogre -> "섀도 라티오스"처럼 아예 다른 포켓몬으로 오역, 더 큰 모델로
    바꿔도 마찬가지였음). 그래서 대신 PokeAPI(포켓몬 공식 다국어 이름을 제공
    하는 무료 오픈 데이터베이스)에서 기본 종 이름만 정확히 조회하고, Mega/
    Shadow 같은 접두어는 항상 같은 규칙이라 기계적으로 붙인다. Therian Forme
    같은 복잡한 폼 설명은 번역 없이 영문 그대로 남는다 - 완벽하진 않지만
    최소한 포켓몬 자체를 잘못 알려주는 일은 없다.
    """
    translated: dict[str, str] = {}
    with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        for name in names:
            ko_prefix, remainder = _strip_known_prefix(name)
            base_name, suffix = _split_form_suffix(remainder)
            ko_base = pokeapi_korean_species_name(client, base_name)
            if ko_base is None:
                continue
            translated[name] = f"{ko_prefix}{ko_base}{suffix}"
    return translated
