"""SSG 크롤러 테스트"""

import pytest

from crawlers.ssg_crawler import SSGCrawler


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """전역 요청 간격/냉각이 단위 테스트를 느리게 만들거나 테스트 간에
    새지 않도록 기본 0으로 초기화.
    (요청 간격/냉각 자체를 검증하는 테스트는 개별적으로 값을 덮어쓴다)"""
    monkeypatch.setattr(SSGCrawler, "MIN_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(SSGCrawler, "RATE_LIMIT_COOLDOWN", 0.0)
    monkeypatch.setattr(SSGCrawler, "_cooldown_until", 0.0)
    monkeypatch.setattr(SSGCrawler, "_consecutive_403", 0)
    monkeypatch.setattr(SSGCrawler, "_fast_fail_until", 0.0)

HTML_SALE_WITH_DELIVERY = """
<html><body>
<div class="cdtl_new_price notranslate"><em class="ssg_price">45,000</em></div>
<ul class="cdtl_dl cdtl_delivery_fee"><li><em class="ssg_price">3,000</em></li></ul>
</body></html>
"""

HTML_SALE_AND_COUPON = """
<html><body>
<div class="cdtl_new_price notranslate"><em class="ssg_price">45,000</em></div>
<div class="cdtl_bene_price"><em class="ssg_price">40,500</em></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><a class="cdtl_btn_soldout">일시품절</a></body></html>
"""

HTML_EMPTY = "<html><body><p>x</p></body></html>"

# 쿠폰가/배송비 영역에도 em.ssg_price가 존재 (실사이트 패턴) — 둘 다 문서상
# 실제 판매가보다 앞에 위치. bare fallback이 이들을 건너뛰고 진짜 판매가를
# 찾아야 한다. 앞선 세 선택자(.cdtl_new_price.notranslate, .cdtl_price,
# .price_total)에는 걸리지 않도록 다른 클래스명을 사용한다.
HTML_BARE_FALLBACK_WITH_NOISE = """
<html><body>
<div class="cdtl_bene_price"><em class="ssg_price">40,500</em></div>
<ul class="cdtl_delivery_fee"><li><em class="ssg_price">3,000</em></li></ul>
<div class="some_price_wrap"><em class="ssg_price">45,000</em></div>
</body></html>
"""


def test_sale_price_and_delivery():
    r = SSGCrawler().extract_price(HTML_SALE_WITH_DELIVERY, "http://t")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] is None
    assert r["배송비"] == 3000
    assert r["배송비 여부"] == "유료"
    assert r["최종 가격"] == 48000
    assert r["결과 상태"] == "success"


def test_sale_and_coupon_split():
    r = SSGCrawler().extract_price(HTML_SALE_AND_COUPON, "http://t")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] == 40500
    assert r["최종 가격"] == 40500


def test_sold_out():
    r = SSGCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"


def test_not_found():
    r = SSGCrawler().extract_price(HTML_EMPTY, "http://t")
    assert r["결과 상태"] == "not_found"


def test_bare_fallback_skips_coupon_and_delivery_em_ssg_price():
    """bare 'em.ssg_price' fallback은 쿠폰가/배송비 컨테이너 내부 요소를
    건너뛰고 진짜 판매가 영역의 em.ssg_price를 찾아야 한다."""
    r = SSGCrawler().extract_price(HTML_BARE_FALLBACK_WITH_NOISE, "http://t")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] == 40500


# 판매가 em과 쿠폰 컨테이너 내부 em의 마크업이 byte-identical한 경우 —
# BS4의 == 는 마크업 동등성이라 동일성(id) 비교가 아니면 진짜 판매가까지
# 건너뛰게 된다.
HTML_BARE_FALLBACK_IDENTICAL_MARKUP = """
<html><body>
<div class="cdtl_bene_price"><em class="ssg_price">40,500</em></div>
<div class="some_price_wrap"><em class="ssg_price">40,500</em></div>
</body></html>
"""


def test_bare_fallback_identical_markup_outside_excluded_container():
    """제외 컨테이너 밖의 판매가 em이 컨테이너 내부 em과 마크업이 같아도
    건너뛰지 않고 판매가로 인식해야 한다."""
    r = SSGCrawler().extract_price(HTML_BARE_FALLBACK_IDENTICAL_MARKUP, "http://t")
    assert r["판매가"] == 40500


# --- www.ssg.com 봇 차단 → 서브도메인 우회 ---
# www.ssg.com(및 bare ssg.com, emart.ssg.com)은 Akamai가 상품 페이지를 상시
# 차단하지만, 같은 itemId를 shinsegaemall.ssg.com으로 열면 차단 없이 열리고
# 가격도 동일하다 (2026-07 실측). 차단 도메인은 서브도메인으로 재작성해
# HTTP 수집하고, 재작성 후에도 실패하면 재시도 없이 명확한 오류로 기록한다.

def test_blocked_host_rewritten_to_subdomain(monkeypatch):
    calls = []

    def fake_get(self, url):
        calls.append(url)
        # crawl_price의 짧은-HTML 재시도(<2000B)를 피하기 위한 패딩
        return HTML_SALE_WITH_DELIVERY + "<!--" + "x" * 2000 + "-->"

    monkeypatch.setattr(SSGCrawler, "_http_get", fake_get)
    r = SSGCrawler().crawl_price(
        "https://www.ssg.com/item/itemView.ssg?itemId=1&siteNo=6004&itemSsgCollectYn=N"
    )
    assert calls == [
        "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1&siteNo=6004&itemSsgCollectYn=N"
    ]
    assert r["결과 상태"] == "success"
    assert r["판매가"] == 45000
    # 결과의 상품 url은 시트 원본 그대로 유지
    assert r["상품 url"].startswith("https://www.ssg.com/")


def test_bare_host_and_http_scheme_rewritten(monkeypatch):
    calls = []

    def fake_get(self, url):
        calls.append(url)
        # crawl_price의 짧은-HTML 재시도(<2000B)를 피하기 위한 패딩
        return HTML_SALE_WITH_DELIVERY + "<!--" + "x" * 2000 + "-->"

    monkeypatch.setattr(SSGCrawler, "_http_get", fake_get)
    SSGCrawler().crawl_price("http://ssg.com/item/itemView.ssg?itemId=2")
    assert calls == ["https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=2"]


def test_rewritten_fetch_failure_reports_clear_error_and_retries(monkeypatch):
    """우회 요청 실패는 레이트리밋(일시적)일 수 있으므로 crawl_price의
    재시도를 타야 하고, 최종 실패 시 명확한 메시지를 남겨야 한다."""
    calls = []

    def fake_get(self, url):
        calls.append(url)
        return None

    monkeypatch.setattr(SSGCrawler, "_http_get", fake_get)
    r = SSGCrawler().crawl_price(
        "https://www.ssg.com/item/itemView.ssg?itemId=1", max_retries=1
    )
    assert r["결과 상태"] == "error"
    assert "우회 요청도 실패" in r["에러 발생"]
    assert len(calls) == 1             # max_retries=1 → 시도 1회


def test_fetch_page_rate_limited(monkeypatch):
    """shinsegaemall도 burst 요청 시 일시 차단(429)되므로 클래스 전역으로
    요청 간 최소 간격을 강제해야 한다."""
    import time

    monkeypatch.setattr(SSGCrawler, "_http_get", lambda self, url: "<html></html>")
    monkeypatch.setattr(SSGCrawler, "MIN_REQUEST_INTERVAL", 0.3)
    monkeypatch.setattr(SSGCrawler, "_last_fetch_at", 0.0)

    a, b = SSGCrawler(), SSGCrawler()
    start = time.monotonic()
    a.fetch_page("https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1")
    b.fetch_page("https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=2")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.3


def test_subdomain_url_not_rewritten(monkeypatch):
    calls = []

    def fake_get(self, url):
        calls.append(url)
        return None

    monkeypatch.setattr(SSGCrawler, "_http_get", fake_get)
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1"
    r = SSGCrawler().crawl_price(url, max_retries=1)
    assert calls == [url]              # 재작성 없음
    assert r["결과 상태"] == "error"
    assert "우회" not in r["에러 발생"]   # 일반 실패 메시지 유지


def test_fetch_failure_triggers_cooldown(monkeypatch):
    """요청 실패(일시 차단 추정) 후 다음 요청은 냉각 시간이 지난 뒤에
    나가야 한다."""
    import time

    results = [None, "<html>ok</html>"]
    monkeypatch.setattr(
        SSGCrawler, "_http_get", lambda self, url: results.pop(0)
    )
    monkeypatch.setattr(SSGCrawler, "RATE_LIMIT_COOLDOWN", 0.4)
    monkeypatch.setattr(SSGCrawler, "_cooldown_until", 0.0)

    c = SSGCrawler()
    url = "https://www.ssg.com/item/itemView.ssg?itemId=1"
    # start는 냉각이 설정되는 첫 호출 이전에 측정 — 이후에 측정하면
    # 냉각 설정~측정 사이 지연만큼 잔여 냉각이 줄어 간헐 실패한다
    start = time.monotonic()
    with pytest.raises(Exception, match="우회 요청도 실패"):
        c.fetch_page(url)
    assert c.fetch_page(url) == "<html>ok</html>"
    assert time.monotonic() - start >= 0.4


# --- 조건부 배송비 (www 새 DOM area-detail 등) ---
# "배송비 : N원" + "M원 이상 구매 시 무료배송" 안내가 있는 경우,
# 상품 가격이 M 이상이면 배송비 0원, 미만이면 N원으로 계산해야 한다.
HTML_CONDITIONAL_DELIVERY = """
<html><body>
<div class="cdtl_new_price notranslate"><em class="ssg_price">48,545</em></div>
<div class="area-detail" data-type="1">
  <dl>
    <dt>배송비 : 3,000원</dt>
    <dd>500,000원 이상 구매 시 무료배송</dd>
    <dt>지역별 추가 배송비</dt>
    <dd>제주 4,000원 / 도서산간 6,000원</dd>
  </dl>
</div>
</body></html>
"""

HTML_CONDITIONAL_DELIVERY_OVER = HTML_CONDITIONAL_DELIVERY.replace("48,545", "600,000")

HTML_RETURN_FEE_ONLY = """
<html><body>
<div class="cdtl_new_price notranslate"><em class="ssg_price">48,545</em></div>
<div class="area-detail"><dl>
  <dt>반품배송비 : 2,500원</dt>
  <dt>교환배송비 : 5,000원</dt>
</dl></div>
</body></html>
"""


def test_conditional_delivery_below_threshold():
    r = SSGCrawler().extract_price(HTML_CONDITIONAL_DELIVERY, "http://t")
    assert r["판매가"] == 48545
    assert r["배송비"] == 3000
    assert r["배송비 여부"] == "유료"
    assert r["최종 가격"] == 51545


def test_conditional_delivery_above_threshold_is_free():
    r = SSGCrawler().extract_price(HTML_CONDITIONAL_DELIVERY_OVER, "http://t")
    assert r["판매가"] == 600000
    assert r["배송비"] == 0
    assert r["배송비 여부"] == "무료"


def test_return_exchange_fee_not_mistaken_for_delivery():
    r = SSGCrawler().extract_price(HTML_RETURN_FEE_ONLY, "http://t")
    assert r["배송비"] == 0
    assert r["배송비 여부"] == "무료"


# --- TLS 지문 위장 (curl_cffi) ---
# 2026-07-31: SSG가 python-requests의 TLS 지문(JA3)을 첫 요청부터 403으로
# 차단하기 시작 (shinsegaemall 포함 전 서브도메인 실측). curl_cffi의
# chrome 위장으로는 동일 페이지가 200으로 열림을 실측 확인 → HTTP 수집을
# curl_cffi(impersonate="chrome")로 전환한다.

def _patch_fake_curl_session(monkeypatch, status_code=200, text="<html>ok</html>"):
    import curl_cffi.requests as curl_requests

    created = {}

    class _FakeResp:
        pass

    class _FakeSession:
        def __init__(self, impersonate=None, **kwargs):
            created["impersonate"] = impersonate

        def get(self, url, timeout=None, **kwargs):
            created["url"] = url
            r = _FakeResp()
            r.status_code = status_code
            r.text = text
            return r

    monkeypatch.setattr(curl_requests, "Session", _FakeSession)
    monkeypatch.setattr(SSGCrawler, "_http_session", None)
    return created


def test_http_get_uses_chrome_impersonation(monkeypatch):
    created = _patch_fake_curl_session(monkeypatch, text="<html>가격</html>")
    c = SSGCrawler()
    assert c._http_get("https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1") == "<html>가격</html>"
    assert created["impersonate"] == "chrome"
    assert created["url"].endswith("itemId=1")


def test_http_get_non_200_returns_none(monkeypatch):
    _patch_fake_curl_session(monkeypatch, status_code=403, text="denied")
    assert SSGCrawler()._http_get("https://shinsegaemall.ssg.com/x") is None


def test_http_session_shared_across_instances(monkeypatch):
    """쿠키(ak_bmsc 등) 누적을 위해 세션은 클래스 전역으로 재사용한다."""
    import curl_cffi.requests as curl_requests

    count = []

    class _FakeSession:
        def __init__(self, **kwargs):
            count.append(1)

        def get(self, url, timeout=None, **kwargs):
            r = type("R", (), {"status_code": 200, "text": "ok"})()
            return r

    monkeypatch.setattr(curl_requests, "Session", _FakeSession)
    monkeypatch.setattr(SSGCrawler, "_http_session", None)
    a, b = SSGCrawler(), SSGCrawler()
    a._http_get("https://shinsegaemall.ssg.com/1")
    b._http_get("https://shinsegaemall.ssg.com/2")
    assert len(count) == 1


# --- IP 차단 서킷 브레이커 ---
# Akamai 차단은 요청이 올 때마다 점수가 갱신되는 방식이라, 차단 중에도
# 191개 상품 × 4~5 URL을 계속 요청하면 차단이 영원히 안 풀리는 악순환이
# 된다 (2026-07-31 실측). 연속 403이 임계치에 달하면 일정 시간 요청 자체를
# 생략하고 명확한 오류로 빠르게 기록한다.

def _patch_curl_with_statuses(monkeypatch, statuses):
    """statuses 순서대로 응답하는 가짜 curl 세션. 호출된 URL 목록을 반환."""
    import curl_cffi.requests as curl_requests

    calls = []

    class _FakeSession:
        def __init__(self, **kwargs):
            pass

        def get(self, url, timeout=None, **kwargs):
            calls.append(url)
            code = statuses.pop(0) if statuses else 403
            # 200이면 가격 마크업 포함 (crawl_price의 짧은-HTML 재시도 회피 패딩)
            text = HTML_SALE_WITH_DELIVERY + "<!--" + "x" * 2000 + "-->"
            return type("R", (), {"status_code": code, "text": text})()

    monkeypatch.setattr(curl_requests, "Session", _FakeSession)
    monkeypatch.setattr(SSGCrawler, "_http_session", None)
    return calls


def test_consecutive_403_trips_circuit_breaker(monkeypatch):
    monkeypatch.setattr(SSGCrawler, "BLOCK_STREAK_THRESHOLD", 3)
    calls = _patch_curl_with_statuses(monkeypatch, [403, 403, 403])

    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId={}"
    for i in range(3):
        c.crawl_price(url.format(i), max_retries=1)
    assert len(calls) == 3

    # 임계치 도달 후에는 HTTP 요청 없이 즉시 명확한 오류
    r = c.crawl_price(url.format(99), max_retries=1)
    assert len(calls) == 3               # 추가 요청 없음
    assert r["결과 상태"] == "error"
    assert "차단 감지" in r["에러 발생"]


def test_success_resets_403_streak(monkeypatch):
    monkeypatch.setattr(SSGCrawler, "BLOCK_STREAK_THRESHOLD", 3)
    calls = _patch_curl_with_statuses(monkeypatch, [403, 403, 200, 403, 403])

    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId={}"
    for i in range(5):
        c.crawl_price(url.format(i), max_retries=1)
    # 중간 200이 streak을 리셋 → 차단 미발동, 5회 모두 실제 요청
    assert len(calls) == 5
    c.crawl_price(url.format(99), max_retries=1)
    assert len(calls) == 6


def test_circuit_breaker_expires(monkeypatch):
    monkeypatch.setattr(SSGCrawler, "BLOCK_STREAK_THRESHOLD", 1)
    monkeypatch.setattr(SSGCrawler, "BLOCK_FAST_FAIL_DURATION", 0.2)
    calls = _patch_curl_with_statuses(monkeypatch, [403, 200])

    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1"
    c.crawl_price(url, max_retries=1)    # 403 → 차단 발동
    c.crawl_price(url, max_retries=1)    # 생략됨
    assert len(calls) == 1

    import time
    time.sleep(0.25)                     # 차단 만료
    r = c.crawl_price(url, max_retries=1)
    assert len(calls) == 2
    assert r["결과 상태"] == "success"
