"""CJ온스타일 크롤러 테스트"""

import pytest

from crawlers.cj_crawler import CJCrawler


@pytest.fixture(autouse=True)
def _reset_stealthy_session():
    """클래스 공유 세션이 테스트 간 누수되지 않도록 초기화."""
    CJCrawler._stealthy_session = None
    yield
    CJCrawler._stealthy_session = None

HTML_SALE_AND_COUPON = """
<html><body>
<div class="item_price"><strong class="ff_price">43,000</strong></div>
<div class="coupon_price"><span class="ff_price">39,900</span></div>
<div class="delivery_fees"><strong>2,500원</strong></div>
</body></html>
"""

HTML_SALE_ONLY = """
<html><body>
<div class="item_price"><strong class="ff_price">43,000</strong></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><button class="btn_soldout">품절</button></body></html>
"""


def test_sale_and_coupon_split():
    r = CJCrawler().extract_price(HTML_SALE_AND_COUPON, "http://t")
    assert r["판매가"] == 43000
    assert r["쿠폰적용가"] == 39900
    assert r["배송비"] == 2500
    assert r["최종 가격"] == 42400
    assert r["결과 상태"] == "success"


def test_sale_only():
    r = CJCrawler().extract_price(HTML_SALE_ONLY, "http://t")
    assert r["판매가"] == 43000
    assert r["쿠폰적용가"] is None
    assert r["최종 가격"] == 43000


def test_sold_out():
    r = CJCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"


# --- scrapling StealthySession 전환 (2026-07) ---
# CJ 상품 페이지는 SPA라 정적 HTML에 가격이 없고, headless Chrome(Selenium)은
# 서버에서 봇 감지로 빈 페이지를 받는다. Camoufox(StealthySession)는 headless로도
# 감지를 통과함을 실측 확인 → 브라우저 방식을 scrapling으로 교체.


class _FakePage:
    def __init__(self, status=200, html="<html>rendered</html>"):
        self.status = status
        self.html_content = html


class _FakeStealthySession:
    def __init__(self, pages=None, error=None):
        self.pages = pages or []
        self.error = error
        self.fetch_calls = []
        self.closed = False

    def fetch(self, url, **kwargs):
        self.fetch_calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.pages.pop(0) if self.pages else _FakePage()

    def close(self):
        self.closed = True


def test_no_longer_uses_selenium():
    """CJ는 이제 Selenium(Chrome)이 아니라 scrapling 세션을 쓴다."""
    assert CJCrawler().use_selenium is False


def test_fetch_page_returns_rendered_html(monkeypatch):
    fake = _FakeStealthySession(pages=[_FakePage(html="<html>가격 43,000</html>")])
    monkeypatch.setattr(CJCrawler, "_create_stealthy_session", classmethod(lambda cls: fake))

    html = CJCrawler().fetch_page("http://t/item/1")
    assert html == "<html>가격 43,000</html>"
    url, kwargs = fake.fetch_calls[0]
    assert url == "http://t/item/1"
    # 가격 또는 품절 요소 중 먼저 나타나는 쪽까지 대기해야 한다
    # (품절 페이지에는 가격 요소가 없어 가격만 기다리면 타임아웃)
    assert ".ff_price" in kwargs["wait_selector"]
    assert ".btn_soldout" in kwargs["wait_selector"]


def test_session_created_once_and_shared(monkeypatch):
    created = []

    def _create(cls):
        s = _FakeStealthySession()
        created.append(s)
        return s

    monkeypatch.setattr(CJCrawler, "_create_stealthy_session", classmethod(_create))

    a, b = CJCrawler(), CJCrawler()
    a.fetch_page("http://t/1")
    b.fetch_page("http://t/2")
    a.fetch_page("http://t/3")
    assert len(created) == 1
    assert len(created[0].fetch_calls) == 3


def test_fetch_error_returns_none_and_resets_session(monkeypatch):
    fake = _FakeStealthySession(error=RuntimeError("browser died"))
    monkeypatch.setattr(CJCrawler, "_create_stealthy_session", classmethod(lambda cls: fake))

    assert CJCrawler().fetch_page("http://t/1") is None
    assert fake.closed is True
    assert CJCrawler._stealthy_session is None  # 다음 요청에서 재생성


def test_fetch_non_200_returns_none_keeps_session(monkeypatch):
    fake = _FakeStealthySession(pages=[_FakePage(status=403, html="blocked")])
    monkeypatch.setattr(CJCrawler, "_create_stealthy_session", classmethod(lambda cls: fake))

    assert CJCrawler().fetch_page("http://t/1") is None
    assert fake.closed is False
    assert CJCrawler._stealthy_session is fake  # 브라우저는 유지 (재시도용)
