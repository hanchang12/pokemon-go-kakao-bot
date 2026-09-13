"""공식 한국어 Pokemon GO 뉴스(pokemongo.com/ko)에서 이벤트 기사를 수집한다.

공식 한국 사이트가 1순위 소스다. 기사 본문에는
``한국시간 2026년 9월 29일 10:00부터 10월 5일 20:00까지`` 형태로 KST 일정이
그대로 적혀 있고, 한국 한정 이벤트도 이곳에만 실린다.

다만 레이드아워·스포트라이트아워 같은 주간 반복 일정은 공식 한국 사이트에
게시되지 않으므로 ``community_source``(포케토리, 포고지지)가 그 부분을 보완한다.
"""

from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
import re
from urllib.parse import urljoin

import httpx


NEWS_URL = "https://pokemongo.com/ko/news"
ARTICLE_PATTERN = re.compile(r"/ko/news/([a-z0-9\-]+)")
PUBLISHED_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
USER_AGENT = "pokemon-go-kakao-bot/1.0"

# 기사 본문만 남기기 위해 통째로 버리는 요소들
DROP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "svg"}

# Kept small on purpose: this text goes straight into the structuring LLM
# call, and slower providers (e.g. NVIDIA NIM's free tier) can time out well
# before finishing a much larger prompt. 12 articles covers roughly the last
# 2-3 weeks of announcements at this site's typical posting cadence.
MAX_ARTICLES = 12
MAX_ARTICLE_CHARS = 2000


@dataclass
class Article:
    slug: str
    url: str
    published_at: str | None
    text: str


class ArticleTextParser(HTMLParser):
    """기사 HTML에서 사람이 읽는 텍스트만 뽑아낸다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_TAGS:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag in DROP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "br", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)

    def text(self) -> str:
        joined = " ".join(self.parts)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\s*\n\s*", "\n", joined)
        return re.sub(r"\n{2,}", "\n", joined).strip()


def _get(client: httpx.Client, url: str) -> str:
    response = client.get(url)
    response.raise_for_status()
    return response.text


def list_article_slugs(html: str) -> list[str]:
    """뉴스 목록 HTML에서 기사 slug를 게시 순서대로 뽑는다."""
    seen: list[str] = []
    for match in ARTICLE_PATTERN.finditer(html):
        slug = match.group(1)
        if slug not in seen:
            seen.append(slug)
    return seen


def parse_article(slug: str, html: str) -> Article:
    parser = ArticleTextParser()
    parser.feed(html)
    published = PUBLISHED_PATTERN.search(html)
    return Article(
        slug=slug,
        url=urljoin(NEWS_URL + "/", slug),
        published_at=published.group(0) if published else None,
        text=parser.text()[:MAX_ARTICLE_CHARS],
    )


def fetch_articles(limit: int = MAX_ARTICLES) -> list[Article]:
    articles: list[Article] = []
    with httpx.Client(
        follow_redirects=True, timeout=20, headers={"User-Agent": USER_AGENT}
    ) as client:
        slugs = list_article_slugs(_get(client, NEWS_URL))[:limit]
        for slug in slugs:
            url = urljoin(NEWS_URL + "/", slug)
            try:
                html = _get(client, url)
            except httpx.HTTPError:
                continue
            article = parse_article(slug, html)
            if article.text:
                articles.append(article)
    return articles


def fetch_korean_records(now: datetime) -> str:
    """Gemini에 넘길 공식 한국 뉴스 블록을 만든다."""
    articles = fetch_articles()
    if not articles:
        raise RuntimeError("공식 한국 뉴스에서 기사를 가져오지 못했습니다")

    blocks = []
    for article in articles:
        header = [f"기사 제목/본문 (slug: {article.slug})", f"source_url: {article.url}"]
        if article.published_at:
            header.append(f"게시일: {article.published_at}")
        blocks.append("\n".join(header) + "\n" + article.text)
    return "\n\n=====\n\n".join(blocks)
