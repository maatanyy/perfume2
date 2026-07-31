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

# 판매종료/삭제 상품 URL은 CJ가 메인 페이지로 클라이언트 리다이렉트한다
# (2026-07 실측: title '홈 | CJ온스타일', #main_cont는 메인에만 존재).
HTML_MAIN_REDIRECT = """
<html><head><title>홈 | CJ온스타일</title></head>
<body><div id="main_cont">메인 콘텐츠</div></body></html>
"""


def test_main_redirect_detected_as_discontinued():
    """메인 리다이렉트 페이지는 not_found로 분류하되, 비고(에러)에
    판매종료 추정임을 남겨 사용자가 URL 목록을 정리할 수 있게 한다."""
    r = CJCrawler().extract_price(HTML_MAIN_REDIRECT, "http://t")
    assert r["결과 상태"] == "not_found"
    assert "판매종료" in r["에러 발생"]


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
    # 대기 로직은 page_action으로 수행한다 — wait_selector를 같이 쓰면
    # 선택자가 영원히 안 나타나는 페이지에서 타임아웃이 2배(대기 2번)가 됨
    assert callable(kwargs["page_action"])
    assert "wait_selector" not in kwargs


def test_wait_selector_union():
    # 가격 또는 품절 요소 중 먼저 나타나는 쪽까지 대기해야 한다
    # (품절 페이지에는 가격 요소가 없어 가격만 기다리면 타임아웃)
    parts = CJCrawler()._wait_selector().split(", ")
    assert ".item_price strong.ff_price" in parts
    # 변형 DOM(가격이 .price_area 아래에만 있는 페이지)도 빠르게 매칭되도록
    assert ".price_area .price_txt > strong.ff_price" in parts
    assert ".btn_soldout" in parts
    # 판매종료 상품은 메인으로 리다이렉트되어 가격/품절 요소가 영원히 안
    # 나타난다 — 메인 전용 요소(#main_cont)도 기다려야 15초 타임아웃 대신
    # 리다이렉트 직후(~2초) 바로 not_found로 분류된다 (2026-07 실측)
    assert "#main_cont" in parts
    # bare '.ff_price'는 SPA 셸에 빈 스켈레톤으로 존재해 렌더 전에 매칭됨
    # (2026-07 실측: 간헐적으로 가격 없는 HTML이 반환되어 not_found 오탐)
    # → 대기 조건에서는 제외해야 한다
    assert ".ff_price" not in parts


# --- page_action: 가격 대기 후 배송비 영역 추가 대기 ---
# 배송비 영역(.delivery_fees)은 가격보다 0.01~0.35초 늦게 렌더된다
# (2026-07-31 실측). 가격 출현 즉시 HTML을 캡처하면 그 틈에 배송비가
# 간헐적으로 누락되어 같은 상품의 배송비가 있다 없다 하는 오탐이 생김
# → 가격이 뜬 뒤 배송비 영역을 짧게(cap) 추가 대기한다.

class _FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.first = self

    def wait_for(self, state=None, timeout=None):
        self.page.wait_calls.append((self.selector, timeout))
        if self.selector in self.page.timeout_selectors:
            raise TimeoutError(f"timeout: {self.selector}")

    def count(self):
        return self.page.counts.get(self.selector, 0)


class _FakeDomPage:
    def __init__(self, counts=None, timeout_selectors=()):
        self.wait_calls = []
        self.counts = counts or {}
        self.timeout_selectors = set(timeout_selectors)

    def locator(self, selector):
        return _FakeLocator(self, selector)


def test_page_action_waits_union_then_delivery_when_price_present():
    c = CJCrawler()
    page = _FakeDomPage(counts={c._price_wait_union(): 1})
    assert c._page_action(page) is page
    selectors = [s for s, _ in page.wait_calls]
    assert selectors == [c._wait_selector(), c.DELIVERY_WAIT_SELECTOR]
    # 배송비 대기는 짧은 cap — 영역이 아예 없는 페이지에서 오래 안 기다림
    assert page.wait_calls[1][1] == c.DELIVERY_WAIT_TIMEOUT_MS


def test_page_action_skips_delivery_when_no_price():
    """품절/메인 리다이렉트 페이지에는 가격이 없다 — 배송비 대기 생략."""
    c = CJCrawler()
    page = _FakeDomPage(counts={})  # 가격 요소 0개
    c._page_action(page)
    selectors = [s for s, _ in page.wait_calls]
    assert c.DELIVERY_WAIT_SELECTOR not in selectors


def test_page_action_survives_union_timeout():
    c = CJCrawler()
    page = _FakeDomPage(timeout_selectors={c._wait_selector()})
    assert c._page_action(page) is page  # 예외 없이 반환
    assert len(page.wait_calls) == 1     # 배송비 대기까지 가지 않음


def test_page_action_survives_delivery_timeout():
    c = CJCrawler()
    page = _FakeDomPage(
        counts={c._price_wait_union(): 1},
        timeout_selectors={c.DELIVERY_WAIT_SELECTOR},
    )
    assert c._page_action(page) is page  # 예외 없이 반환


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


def test_fetch_runs_on_single_dedicated_thread(monkeypatch):
    """StealthySession은 Playwright 기반이라 브라우저를 시작한 스레드에서만
    조작할 수 있다. 서버(2026-07 실측)에서는 엔진 워커 스레드들이 번갈아
    fetch_page를 호출 → 스레드가 바뀔 때마다 예외 → 브라우저 재생성 반복 →
    못 닫은 좀비 브라우저 7개 누적으로 메모리 고갈. 따라서 어느 스레드가
    호출하든 세션 생성과 fetch는 전용 스레드 1개에서만 실행되어야 한다."""
    import threading as th

    create_threads = []
    fetch_threads = []

    class _ThreadRecordingSession(_FakeStealthySession):
        def fetch(self, url, **kwargs):
            fetch_threads.append(th.get_ident())
            return super().fetch(url, **kwargs)

    def _create(cls):
        create_threads.append(th.get_ident())
        return _ThreadRecordingSession()

    monkeypatch.setattr(CJCrawler, "_create_stealthy_session", classmethod(_create))

    caller_threads = []

    def _call():
        caller_threads.append(th.get_ident())
        assert CJCrawler().fetch_page("http://t/1") == "<html>rendered</html>"

    for _ in range(2):
        t = th.Thread(target=_call)
        t.start()
        t.join()

    assert len(set(fetch_threads)) == 1  # 브라우저 조작은 항상 같은 스레드
    assert set(create_threads) == set(fetch_threads)  # 세션 생성도 같은 스레드
    assert set(fetch_threads).isdisjoint(caller_threads)  # 호출자 스레드가 아님


def test_fetch_non_200_returns_none_keeps_session(monkeypatch):
    fake = _FakeStealthySession(pages=[_FakePage(status=403, html="blocked")])
    monkeypatch.setattr(CJCrawler, "_create_stealthy_session", classmethod(lambda cls: fake))

    assert CJCrawler().fetch_page("http://t/1") is None
    assert fake.closed is False
    assert CJCrawler._stealthy_session is fake  # 브라우저는 유지 (재시도용)
