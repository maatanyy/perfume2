"""롯데아이몰 크롤러 테스트"""

from crawlers.lotte_crawler import LotteCrawler

# 실사이트 검증(Task 10)에서 확인한 실제 DOM 구조:
#   <span class="origin"><span class="line">189,000</span> 원</span>  (할인 전 정가)
#   <div class="price"><div class="percent">5%</div>
#     <div class="final"><span class="num">179,550</span>원</div></div>  (실제 판매가)
# `.origin .num`(존재하지 않음, 실제는 `.line`)은 매칭되지 않고 `.final .num`이
# 실제 표시 판매가였다. 쿠폰적용가는 페이지에 사전 계산된 요소가 없어 미표시.
HTML_REAL_DOM = """
<html><body>
<div class="price_product price_black">
  <div class="wrap_price">
    <span class="origin"><span class="line">189,000</span> 원</span>
    <div class="price">
      <div class="percent"><em><span class="num">5</span><span class="txt">%</span></em></div>
      <div class="final">
        <span class="num">179,550</span><span class="txt">원</span>
      </div>
    </div>
  </div>
</div>
<div class="row_product delivery"><div class="cont"><p>배송비 3,000원 (300,000원 이상 무료)</p></div></div>
</body></html>
"""

HTML_SALE_PRC_FALLBACK = """
<html><body>
<div class="sale_prc">59,000</div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><div class="btn_soldout_area">품절</div></body></html>
"""

HTML_EMPTY = "<html><body><p>내용 없음</p></body></html>"


def test_real_dom_extracts_final_as_sale_price():
    """실사이트 DOM(.final .num)이 판매가로 추출되고, 쿠폰적용가는 표시 요소가
    없으므로 None이어야 한다(쿠폰 할인은 JS 데이터에만 있고 사전 계산된 최종가
    DOM 요소가 없음을 실사이트 검증에서 확인함)."""
    r = LotteCrawler().extract_price(HTML_REAL_DOM, "http://t")
    assert r["판매가"] == 179550
    assert r["쿠폰적용가"] is None
    assert r["상품 가격"] == 179550
    assert r["배송비"] == 3000
    assert r["최종 가격"] == 182550
    assert r["결과 상태"] == "success"


def test_sale_prc_fallback():
    r = LotteCrawler().extract_price(HTML_SALE_PRC_FALLBACK, "http://t")
    assert r["판매가"] == 59000
    assert r["결과 상태"] == "success"


def test_sold_out():
    r = LotteCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"


def test_not_found():
    r = LotteCrawler().extract_price(HTML_EMPTY, "http://t")
    assert r["결과 상태"] == "not_found"


class _RecordingSession:
    """세션 호출 기록용 스텁 (requests.Session 대체)."""

    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)

        class _Resp:
            text = "<html>main</html>"

            def raise_for_status(self):
                pass

        return _Resp()


def test_fetch_warms_up_main_page_once(monkeypatch):
    """상품 URL 직행은 쿠키 없음 패턴으로 403 차단된다 (2026-07 실측:
    메인 페이지 방문으로 쿠키 수신 후 같은 세션은 통과). 첫 요청 전에
    메인 페이지 워밍업이 정확히 1회 수행되어야 한다."""
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(
        BaseCrawler, "fetch_page", lambda self, url, wait_time=2: "<html>ok</html>"
    )
    monkeypatch.setattr(LotteCrawler, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(LotteCrawler, "_last_fetch_at", 0.0)
    monkeypatch.setattr(LotteCrawler, "_cooldown_until", 0.0)

    c = LotteCrawler()
    c.session = _RecordingSession()
    c.fetch_page("http://t/1")
    c.fetch_page("http://t/2")
    assert c.session.calls == [LotteCrawler.WARMUP_URL]


def test_fetch_failure_resets_warmup(monkeypatch):
    """요청 실패(403 추정) 후에는 쿠키가 오염됐을 수 있으므로 다음
    요청 전에 다시 워밍업해야 한다."""
    from crawlers.base_crawler import BaseCrawler

    results = [None, "<html>ok</html>"]
    monkeypatch.setattr(
        BaseCrawler, "fetch_page", lambda self, url, wait_time=2: results.pop(0)
    )
    monkeypatch.setattr(LotteCrawler, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(LotteCrawler, "RATE_LIMIT_COOLDOWN", 0.0)
    monkeypatch.setattr(LotteCrawler, "_last_fetch_at", 0.0)
    monkeypatch.setattr(LotteCrawler, "_cooldown_until", 0.0)

    c = LotteCrawler()
    c.session = _RecordingSession()
    assert c.fetch_page("http://t/1") is None       # 워밍업 1회 + 실패
    assert c.fetch_page("http://t/1") == "<html>ok</html>"  # 재워밍업 후 성공
    assert c.session.calls == [LotteCrawler.WARMUP_URL, LotteCrawler.WARMUP_URL]


def test_warmup_failure_does_not_block_fetch(monkeypatch):
    """워밍업 요청 자체가 실패해도 본 요청은 그대로 진행되어야 한다."""
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(
        BaseCrawler, "fetch_page", lambda self, url, wait_time=2: "<html>ok</html>"
    )
    monkeypatch.setattr(LotteCrawler, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(LotteCrawler, "_last_fetch_at", 0.0)
    monkeypatch.setattr(LotteCrawler, "_cooldown_until", 0.0)

    class _FailingSession:
        def get(self, url, **kwargs):
            raise RuntimeError("connection error")

    c = LotteCrawler()
    c.session = _FailingSession()
    assert c.fetch_page("http://t/1") == "<html>ok</html>"


def test_fetch_page_rate_limited(monkeypatch):
    """롯데는 동시 burst 시 안티봇 403이 발생하므로, 인스턴스/스레드와
    무관하게 클래스 전역으로 요청 간 최소 간격을 강제해야 한다."""
    import time
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(BaseCrawler, "fetch_page", lambda self, url, wait_time=2: "<html></html>")
    monkeypatch.setattr(LotteCrawler, "MIN_REQUEST_INTERVAL", 0.3)
    monkeypatch.setattr(LotteCrawler, "_last_fetch_at", 0.0)

    a, b = LotteCrawler(), LotteCrawler()
    a.session, b.session = _RecordingSession(), _RecordingSession()
    start = time.monotonic()
    a.fetch_page("http://t/1")
    b.fetch_page("http://t/2")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.3


def test_fetch_failure_triggers_cooldown(monkeypatch):
    """요청 실패(일시 차단 추정) 후 다음 요청은 냉각 시간이 지난 뒤에
    나가야 한다 (롤링 윈도우 403 회복용)."""
    import time
    from crawlers.base_crawler import BaseCrawler

    results = [None, "<html>ok</html>"]
    monkeypatch.setattr(
        BaseCrawler, "fetch_page", lambda self, url, wait_time=2: results.pop(0)
    )
    monkeypatch.setattr(LotteCrawler, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(LotteCrawler, "RATE_LIMIT_COOLDOWN", 0.4)
    monkeypatch.setattr(LotteCrawler, "_last_fetch_at", 0.0)
    monkeypatch.setattr(LotteCrawler, "_cooldown_until", 0.0)

    c = LotteCrawler()
    c.session = _RecordingSession()
    assert c.fetch_page("http://t/1") is None   # 실패 → 냉각 설정
    start = time.monotonic()
    assert c.fetch_page("http://t/2") == "<html>ok</html>"
    assert time.monotonic() - start >= 0.4
