from datetime import datetime
from zoneinfo import ZoneInfo

from app import korean_source


KST = ZoneInfo("Asia/Seoul")

NEWS_HTML = """
<html><body>
  <a href="/ko/gofest">GO Fest</a>
  <a href="/ko/news/harvest-festival-2026">수확 축제</a>
  <a href="/ko/news/weekly-branching-tr-korea-2026">주간 릴레이</a>
  <a href="/ko/news/harvest-festival-2026">중복 링크</a>
</body></html>
"""

ARTICLE_HTML = """
<html><head><script>var published="2026-09-07T17:00:00";</script></head>
<body>
  <nav>메뉴 항목</nav>
  <article>
    <h1>풍성한 "수확 축제"를 즐겨요!</h1>
    <p>수확 축제: 과사삭벌레 모으기</p>
    <p>한국시간 2026년 9월 29일 10:00부터 10월 5일 20:00까지</p>
  </article>
  <footer>푸터 문구</footer>
</body></html>
"""


def test_list_article_slugs_keeps_order_and_drops_duplicates():
    slugs = korean_source.list_article_slugs(NEWS_HTML)

    assert slugs == ["harvest-festival-2026", "weekly-branching-tr-korea-2026"]


def test_parse_article_extracts_body_published_date_and_url():
    article = korean_source.parse_article("harvest-festival-2026", ARTICLE_HTML)

    assert article.url == "https://pokemongo.com/ko/news/harvest-festival-2026"
    assert article.published_at == "2026-09-07T17:00:00"
    assert "수확 축제: 과사삭벌레 모으기" in article.text
    assert "한국시간 2026년 9월 29일 10:00부터 10월 5일 20:00까지" in article.text


def test_parse_article_drops_chrome_and_scripts():
    article = korean_source.parse_article("harvest-festival-2026", ARTICLE_HTML)

    assert "메뉴 항목" not in article.text
    assert "푸터 문구" not in article.text
    assert "var published" not in article.text


def test_fetch_korean_records_labels_each_article(monkeypatch):
    monkeypatch.setattr(
        korean_source,
        "fetch_articles",
        lambda limit=korean_source.MAX_ARTICLES: [
            korean_source.parse_article("harvest-festival-2026", ARTICLE_HTML)
        ],
    )

    records = korean_source.fetch_korean_records(datetime(2026, 9, 13, tzinfo=KST))

    assert "slug: harvest-festival-2026" in records
    assert "source_url: https://pokemongo.com/ko/news/harvest-festival-2026" in records
    assert "게시일: 2026-09-07T17:00:00" in records
