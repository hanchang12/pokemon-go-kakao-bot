"""한국 커뮤니티 사이트(포케토리, 포고지지)에서 주간 반복 일정을 가져온다.

공식 한국 뉴스(pokemongo.com/ko)는 레이드아워·스포트라이트아워·맥스먼데이 같은
주간 반복 일정과 요일별 보너스(쇼케이스 투스데이, 우정 프라이데이 등)를 싣지
않는다. 이 부분은 매주 갱신되는 한국 커뮤니티 사이트의 일정 정리글로 보완한다.

- 포케토리(poketory.com)의 "이번 주의 이벤트 및 보너스 일정" 글은 고정 URL로
  매주 새로 갱신되며, 한국시간 기준 요일·시각이 표 형태로 정리돼 있다.
- 포고지지(pgsharp-info.com)의 "일정" 게시판은 레이드 로테이션(전설/메가)과
  스포트라이트아워 등장 포켓몬을 월 단위로 정리한다.
"""

import re

import httpx

from app.korean_source import ArticleTextParser


POKETORY_WEEKLY_URL = "https://poketory.com/pokemongo-weekly-event/"
PGSHARP_NEWS_URL = "https://www.pgsharp-info.com/bbs/board.php?bo_table=news&sca=%EC%9D%BC%EC%A0%95"
PGSHARP_ARTICLE_URL = "https://www.pgsharp-info.com/bbs/board.php?bo_table=news&wr_id={wr_id}"
PGSHARP_ARTICLE_PATTERN = re.compile(r"bo_table=news&wr_id=(\d+)")
USER_AGENT = "pokemon-go-kakao-bot/1.0"

MAX_CHARS = 4000
MAX_PGSHARP_ARTICLES = 3

# 댓글·사이드바가 시작되는 지점을 알리는 표지: 본문은 이 앞까지만 쓴다.
STOP_MARKERS = ["댓글 남기기", "Comments", "로그인한 회원만"]


def _get(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    return response.text


def _extract_body(html: str) -> str:
    parser = ArticleTextParser()
    parser.feed(html)
    text = parser.text()
    cut_at = min((text.index(m) for m in STOP_MARKERS if m in text), default=len(text))
    return text[:cut_at][:MAX_CHARS].strip()


def fetch_poketory_weekly() -> str:
    with httpx.Client(
        follow_redirects=True, timeout=20, headers={"User-Agent": USER_AGENT}
    ) as client:
        html = _get(client, POKETORY_WEEKLY_URL)
    body = _extract_body(html)
    if not body:
        raise RuntimeError("포케토리 주간 일정 본문을 가져오지 못했습니다")
    return f"글 제목/본문 (포케토리 주간 일정)\nsource_url: {POKETORY_WEEKLY_URL}\n{body}"


def _pgsharp_article_ids(html: str, limit: int) -> list[str]:
    seen: list[str] = []
    for match in PGSHARP_ARTICLE_PATTERN.finditer(html):
        wr_id = match.group(1)
        if wr_id not in seen:
            seen.append(wr_id)
        if len(seen) >= limit:
            break
    return seen


def fetch_pgsharp_articles(limit: int = MAX_PGSHARP_ARTICLES) -> list[str]:
    blocks: list[str] = []
    with httpx.Client(
        follow_redirects=True, timeout=20, headers={"User-Agent": USER_AGENT}
    ) as client:
        listing_html = _get(client, PGSHARP_NEWS_URL)
        for wr_id in _pgsharp_article_ids(listing_html, limit):
            url = PGSHARP_ARTICLE_URL.format(wr_id=wr_id)
            try:
                html = _get(client, url)
            except httpx.HTTPError:
                continue
            body = _extract_body(html)
            if body:
                blocks.append(f"글 제목/본문 (포고지지 일정, wr_id={wr_id})\nsource_url: {url}\n{body}")
    return blocks


def fetch_community_records() -> str:
    """Gemini에 넘길 한국 커뮤니티 일정 블록(포케토리 + 포고지지)을 만든다."""
    blocks = [fetch_poketory_weekly()]
    try:
        blocks.extend(fetch_pgsharp_articles())
    except httpx.HTTPError:
        pass  # 포고지지는 보조 소스라, 실패해도 포케토리만으로 계속 진행한다
    return "\n\n=====\n\n".join(blocks)
