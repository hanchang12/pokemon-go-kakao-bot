from app import community_source


POKETORY_HTML = """
<html><head><script>var ga="track";</script></head>
<body>
  <nav>메뉴</nav>
  <article>
    <h1>포켓몬 GO | 게임 일정 - 이번 주의 이벤트 및 보너스 일정</h1>
    <p>16일(수) 18~19시 : 레이드 아워 진행</p>
    <p>17일(목) 18~19시 : 스포트라이트 아워 진행</p>
  </article>
  <div>관련 게시물</div>
  <h2>댓글 남기기</h2>
  <div>이전 댓글: 스포트라이트 좋아요</div>
  <footer>푸터</footer>
</body></html>
"""

PGSHARP_LISTING_HTML = """
<html><body>
  <a href="https://www.pgsharp-info.com/bbs/board.php?bo_table=news&wr_id=1099&sca=%EC%9D%BC%EC%A0%95">달력</a>
  <a href="https://www.pgsharp-info.com/bbs/board.php?bo_table=news&wr_id=1080&sca=%EC%9D%BC%EC%A0%95">달력2</a>
  <a href="https://www.pgsharp-info.com/bbs/board.php?bo_table=news&wr_id=1099&sca=%EC%9D%BC%EC%A0%95">중복</a>
</body></html>
"""

PGSHARP_ARTICLE_HTML = """
<html><body>
  <article>
    <h1>포켓몬고 달력 (9월)</h1>
    <p>스포트 라이트 아워 : 매주 목요일</p>
  </article>
  <div>Comments</div>
  <div>로그인한 회원만 댓글 등록이 가능합니다.</div>
</body></html>
"""


def test_extract_body_stops_before_comments():
    body = community_source._extract_body(POKETORY_HTML)

    assert "레이드 아워 진행" in body
    assert "스포트라이트 아워 진행" in body
    assert "댓글 남기기" not in body
    assert "이전 댓글" not in body
    assert "메뉴" not in body
    assert "푸터" not in body


def test_pgsharp_article_ids_keeps_order_and_drops_duplicates():
    ids = community_source._pgsharp_article_ids(PGSHARP_LISTING_HTML, limit=3)

    assert ids == ["1099", "1080"]


def test_fetch_poketory_weekly_labels_source(monkeypatch):
    class FakeResponse:
        text = POKETORY_HTML

        def raise_for_status(self):
            return None

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url == community_source.POKETORY_WEEKLY_URL
            return FakeResponse()

    monkeypatch.setattr(community_source.httpx, "Client", lambda **kwargs: FakeClient())

    record = community_source.fetch_poketory_weekly()

    assert "source_url: https://poketory.com/pokemongo-weekly-event/" in record
    assert "스포트라이트 아워 진행" in record


def test_fetch_pgsharp_articles_labels_each_source(monkeypatch):
    class FakeResponse:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            return None

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            if url == community_source.PGSHARP_NEWS_URL:
                return FakeResponse(PGSHARP_LISTING_HTML)
            return FakeResponse(PGSHARP_ARTICLE_HTML)

    monkeypatch.setattr(community_source.httpx, "Client", lambda **kwargs: FakeClient())

    records = community_source.fetch_pgsharp_articles(limit=2)

    assert len(records) == 2
    assert "wr_id=1099" in records[0]
    assert "스포트 라이트 아워" in records[0]
