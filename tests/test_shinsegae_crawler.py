"""신세계TV쇼핑 크롤러 테스트 (HTML 픽스처 기반)"""

from crawlers.shinsegae_crawler import ShinsegaeCrawler

# 실사이트 검증(Task 10)에서 확인한 실제 DOM 구조:
#   <div class="div-best">
#     <span class="blind">판매가</span>
#     <span class="_bestPrice">28,600</span><span class="txt-won">원</span>
#   </div>
# `._salePrice`는 실사이트 5개 상품 모두에서 존재하지 않았고, `._bestPrice`가
# 사이트 자체 라벨("판매가")대로 실제 판매가였다. 쿠폰적용가로 사전 계산된
# DOM 요소는 어떤 상품에도 없었음(쿠폰은 발급 모달의 할인율(%)로만 노출).
HTML_REAL_DOM = """
<html><body>
<div class="price--3">
  <div class="div-best">
    <span class="blind">판매가</span>
    <span class="_bestPrice">28,600</span><span class="txt-won">원</span>
  </div>
</div>
</body></html>
"""

# 회귀 테스트: `.sale_price`(공백 없는 별개 클래스)는 할부/적립포인트 안내용
# 요소라 실사이트에서 "300P" 같은 텍스트를 갖고 있었고, 과거 셀렉터 목록에
# 포함되어 있어 판매가를 300원으로 오추출하는 버그가 있었다. 이 클래스가
# 함께 존재해도 오추출되지 않아야 한다.
HTML_WITH_UNRELATED_SALE_PRICE_CLASS = """
<html><body>
<div class="price--3">
  <div class="div-best">
    <span class="blind">판매가</span>
    <span class="_bestPrice">28,600</span><span class="txt-won">원</span>
  </div>
</div>
<div class="benefit-info"><span class="sale_price">6개월 가능 (5만원 이상)</span></div>
<div class="point-info"><span class="sale_price">300P</span></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body>
<div class="prd-detail"><span class="badge-soldout">일시품절</span></div>
</body></html>
"""

HTML_EMPTY = "<html><body><p>내용 없음</p></body></html>"


def test_real_dom_extracts_best_price_as_sale_price():
    r = ShinsegaeCrawler().extract_price(HTML_REAL_DOM, "http://t")
    assert r["판매가"] == 28600
    assert r["쿠폰적용가"] is None
    assert r["상품 가격"] == 28600
    assert r["결과 상태"] == "success"


def test_unrelated_sale_price_class_not_misread():
    r = ShinsegaeCrawler().extract_price(HTML_WITH_UNRELATED_SALE_PRICE_CLASS, "http://t")
    assert r["판매가"] == 28600
    assert r["상품 가격"] == 28600


def test_sold_out_detected():
    r = ShinsegaeCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
    assert r["판매가"] is None


def test_not_found():
    r = ShinsegaeCrawler().extract_price(HTML_EMPTY, "http://t")
    assert r["결과 상태"] == "not_found"


# --- 부하 중 축소 페이지(스텁) 대응 ---
# 2026-08-01 실측: 단건 요청은 343KB 정상 페이지가 오지만, 잡 실행 중
# (동시 요청 부하) 21%가 가격 없는 81KB 축소 페이지를 받아 추출실패로
# 기록됐다. 서버에서 같은 URL 단건 수집은 성공 → 사이트/IP 문제가 아니라
# 요청 몰림 때문. 요청 간격을 두고, 축소 페이지는 1회 재요청한다.

NORMAL_HTML = (
    '<html><body><div class="div-best"><em class="_bestPrice">36,900</em></div>'
    + "<!--" + "x" * 200_000 + "-->"
    + "</body></html>"
)
STUB_HTML = "<html><body><p>일시적 오류</p>" + "<!--" + "x" * 80_000 + "--></body></html>"


def test_stub_page_triggers_one_refetch(monkeypatch):
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 0.0)
    monkeypatch.setattr(ShinsegaeCrawler, "DEGRADED_RETRY_DELAY", 0.0)
    pages = [STUB_HTML, NORMAL_HTML]
    calls = []

    def fake_fetch(self, url, wait_time=2):
        calls.append(url)
        return pages.pop(0)

    monkeypatch.setattr(BaseCrawler, "fetch_page", fake_fetch)
    html = ShinsegaeCrawler().fetch_page("http://t/1")
    assert len(calls) == 2                       # 축소 페이지 → 1회 재요청
    assert "_bestPrice" in html                  # 정상 페이지를 반환


def test_normal_page_not_refetched(monkeypatch):
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 0.0)
    calls = []

    def fake_fetch(self, url, wait_time=2):
        calls.append(url)
        return NORMAL_HTML

    monkeypatch.setattr(BaseCrawler, "fetch_page", fake_fetch)
    ShinsegaeCrawler().fetch_page("http://t/1")
    assert len(calls) == 1


def test_persistent_stub_returns_stub_not_error(monkeypatch):
    """실제로 판매종료된 상품도 축소 페이지를 준다 — 재요청 후에도 같으면
    기존처럼 '추출실패'로 남겨야 한다 (오류로 격상하면 안 됨)."""
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 0.0)
    monkeypatch.setattr(ShinsegaeCrawler, "DEGRADED_RETRY_DELAY", 0.0)
    monkeypatch.setattr(
        BaseCrawler, "fetch_page", lambda self, url, wait_time=2: STUB_HTML
    )
    html = ShinsegaeCrawler().fetch_page("http://t/1")
    assert html == STUB_HTML
    assert ShinsegaeCrawler().extract_price(html, "http://t/1")["결과 상태"] == "not_found"


def test_none_response_not_refetched(monkeypatch):
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 0.0)
    calls = []

    def fake_fetch(self, url, wait_time=2):
        calls.append(url)
        return None

    monkeypatch.setattr(BaseCrawler, "fetch_page", fake_fetch)
    assert ShinsegaeCrawler().fetch_page("http://t/1") is None
    assert len(calls) == 1


def test_request_interval_enforced(monkeypatch):
    """동시 요청이 몰려 축소 페이지를 받지 않도록 클래스 전역 간격을 둔다."""
    import time
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(BaseCrawler, "fetch_page", lambda self, url, wait_time=2: NORMAL_HTML)
    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 0.3)
    monkeypatch.setattr(ShinsegaeCrawler, "_last_fetch_at", 0.0)

    a, b = ShinsegaeCrawler(), ShinsegaeCrawler()
    start = time.monotonic()
    a.fetch_page("http://t/1")
    b.fetch_page("http://t/2")
    assert time.monotonic() - start >= 0.3


# --- 적응형 요청 간격 ---
# 고정 1초 간격은 안전하지만 느리다 (12분56초 → 29분30초). 사이트가 멀쩡할
# 때는 빠르게 가고, 축소 페이지가 나타나면 그때만 간격을 넓힌 뒤 서서히
# 원래대로 돌아온다.

def test_starts_at_base_interval(monkeypatch):
    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", ShinsegaeCrawler.MIN_REQUEST_INTERVAL)
    assert ShinsegaeCrawler._current_interval == ShinsegaeCrawler.MIN_REQUEST_INTERVAL
    assert ShinsegaeCrawler.MIN_REQUEST_INTERVAL < 1.0   # 고정 1초보다 빨라야 한다


def test_degraded_response_widens_interval(monkeypatch):
    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 0.3)
    monkeypatch.setattr(ShinsegaeCrawler, "_good_streak", 0)
    ShinsegaeCrawler._note_degraded()
    assert ShinsegaeCrawler._current_interval > 0.3


def test_interval_capped(monkeypatch):
    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 0.3)
    for _ in range(20):
        ShinsegaeCrawler._note_degraded()
    assert ShinsegaeCrawler._current_interval <= ShinsegaeCrawler.MAX_REQUEST_INTERVAL


def test_good_streak_decays_interval(monkeypatch):
    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", 2.0)
    monkeypatch.setattr(ShinsegaeCrawler, "_good_streak", 0)
    for _ in range(ShinsegaeCrawler.DECAY_AFTER_GOOD * 3):
        ShinsegaeCrawler._note_good()
    assert ShinsegaeCrawler._current_interval < 2.0


def test_interval_never_below_base(monkeypatch):
    monkeypatch.setattr(ShinsegaeCrawler, "_current_interval", ShinsegaeCrawler.MIN_REQUEST_INTERVAL)
    monkeypatch.setattr(ShinsegaeCrawler, "_good_streak", 0)
    for _ in range(200):
        ShinsegaeCrawler._note_good()
    assert ShinsegaeCrawler._current_interval >= ShinsegaeCrawler.MIN_REQUEST_INTERVAL
