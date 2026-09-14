"""외부 티어리스트 사이트(PokéBase)에서 타입별 상위 공격 포켓몬 목록을 가져온다.

정적 데이터인 타입 상성(app/type_chart.py)과 달리 이건 게임 밸런스 패치·신규
포켓몬 출시로 바뀌는 정보라, 매번 수집하지 않고 한 달에 한 번만 갱신한다
(app/scheduler.py에서 마지막 갱신일을 체크).
"""

import re

import httpx

from app.korean_source import ArticleTextParser


TIER_LIST_URL = "https://pokebase.app/pokemon-go/p/best-attackers-by-type"
USER_AGENT = "pokemon-go-kakao-bot/1.0"

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
