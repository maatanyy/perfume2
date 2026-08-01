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
    monkeypatch.setattr(SSGCrawler, "_fast_fail_until", 0.0)
    # 워밍업(실브라우저)이 단위 테스트에서 돌지 않도록 기본은 '워밍업 완료' 상태
    monkeypatch.setattr(SSGCrawler, "_needs_warm", False)
    monkeypatch.setattr(SSGCrawler, "_warm_failures", 0)
    monkeypatch.setattr(SSGCrawler, "_last_warm_at", 0.0)
    monkeypatch.setattr(SSGCrawler, "_warm_ua", None)

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


def test_http_get_uses_browser_impersonation(monkeypatch):
    """requests의 TLS 지문은 차단되므로 실제 브라우저로 위장해야 한다.
    위장 대상은 쿠키를 발급한 워밍업 브라우저 계열을 따른다."""
    monkeypatch.setattr(SSGCrawler, "_camoufox_available", classmethod(lambda cls: False))
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


# --- 서킷 브레이커 만료 ---
# 워밍업 반복 실패로 차단 판정이 나면 일정 시간 요청을 생략하고, 시간이
# 지나면 다시 시도해야 한다 (수동 개입 없이 자동 회복).

def test_circuit_breaker_expires(monkeypatch):
    import time

    monkeypatch.setattr(SSGCrawler, "BLOCK_FAST_FAIL_DURATION", 0.2)
    monkeypatch.setattr(SSGCrawler, "MAX_WARMUP_FAILURES", 1)
    holder, warm_calls = _patch_warmup(
        monkeypatch, statuses=[200], warm_results=[False, True]
    )

    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1"
    assert c._http_get(url) is None          # 워밍업 실패 → 차단 판정
    with pytest.raises(Exception, match="차단 감지"):
        c.fetch_page(url)                    # 요청 생략
    assert len(warm_calls) == 1

    time.sleep(0.25)                         # 차단 만료
    assert c.fetch_page(url) is not None     # 재워밍업 후 정상
    assert len(warm_calls) == 2


# --- 브라우저 쿠키 워밍업 ---
# 2026-08-01 실측: SSG 상품 페이지가 Akamai 센서 쿠키(_abck 등)를 요구하도록
# 바뀌어 순수 HTTP는 항상 403. 실제 브라우저로 메인을 방문해 센서 검증을
# 통과한 쿠키를 확보하면 같은 쿠키로 HTTP 요청이 200으로 열린다
# (headful 필요 — headless로 얻은 쿠키는 거부됨).

class _FakeCookieJar(dict):
    def set(self, name, value, domain=None):
        self[name] = value


class _FakeCurlSession:
    def __init__(self, statuses=None, **kwargs):
        self.statuses = statuses if statuses is not None else []
        self.cookies = _FakeCookieJar()
        self.calls = []

    def get(self, url, timeout=None, headers=None, **kwargs):
        self.calls.append((url, headers or {}))
        code = self.statuses.pop(0) if self.statuses else 200
        text = HTML_SALE_WITH_DELIVERY + "<!--" + "x" * 2000 + "-->"
        return type("R", (), {"status_code": code, "text": text})()


def _patch_warmup(monkeypatch, statuses, warm_results=None):
    """가짜 curl 세션 + 가짜 브라우저 워밍업. (session, warm_calls) 반환."""
    import curl_cffi.requests as curl_requests

    holder = {}

    def _make_session(**kwargs):
        holder["session"] = _FakeCurlSession(statuses=statuses)
        return holder["session"]

    monkeypatch.setattr(curl_requests, "Session", _make_session)
    monkeypatch.setattr(SSGCrawler, "_http_session", None)
    monkeypatch.setattr(SSGCrawler, "_needs_warm", True)
    monkeypatch.setattr(SSGCrawler, "_warm_failures", 0)
    monkeypatch.setattr(SSGCrawler, "_last_warm_at", 0.0)
    monkeypatch.setattr(SSGCrawler, "WARMUP_MIN_INTERVAL", 0.0)

    warm_calls = []
    results = list(warm_results) if warm_results is not None else None

    def fake_warm(cls):
        warm_calls.append(1)
        if results is not None and not results.pop(0):
            return None
        return {
            "cookies": [{"name": "_abck", "value": "sensor-ok", "domain": ".ssg.com"}],
            "ua": "Mozilla/5.0 (Warmed)",
        }

    monkeypatch.setattr(SSGCrawler, "_run_warmup", classmethod(fake_warm))
    return holder, warm_calls


def test_first_request_warms_cookies(monkeypatch):
    holder, warm_calls = _patch_warmup(monkeypatch, statuses=[200])
    c = SSGCrawler()
    assert c._http_get("https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1")
    assert len(warm_calls) == 1
    session = holder["session"]
    assert session.cookies.get("_abck") == "sensor-ok"
    # 브라우저와 같은 UA로 요청해야 센서 쿠키가 유효하다
    assert session.calls[0][1]["User-Agent"] == "Mozilla/5.0 (Warmed)"


def test_warm_reused_across_requests(monkeypatch):
    _, warm_calls = _patch_warmup(monkeypatch, statuses=[200, 200, 200])
    c = SSGCrawler()
    for i in range(3):
        c._http_get(f"https://shinsegaemall.ssg.com/item/itemView.ssg?itemId={i}")
    assert len(warm_calls) == 1     # 워밍업은 1회만


def test_403_triggers_rewarm(monkeypatch):
    _, warm_calls = _patch_warmup(monkeypatch, statuses=[200, 403, 200])
    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId={}"
    c._http_get(url.format(1))      # 200 (워밍업 1회)
    c._http_get(url.format(2))      # 403 → 쿠키 만료 판정
    c._http_get(url.format(3))      # 재워밍업 후 200
    assert len(warm_calls) == 2


def test_repeated_warmup_failure_trips_circuit_breaker(monkeypatch):
    monkeypatch.setattr(SSGCrawler, "MAX_WARMUP_FAILURES", 2)
    _, warm_calls = _patch_warmup(
        monkeypatch, statuses=[], warm_results=[False, False]
    )
    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1"
    assert c._http_get(url) is None
    assert c._http_get(url) is None
    assert len(warm_calls) == 2
    # 서킷 브레이커 발동 — 이후엔 요청/워밍업 없이 즉시 실패
    with pytest.raises(Exception, match="차단 감지"):
        c.fetch_page(url)
    assert len(warm_calls) == 2


def test_429_does_not_trigger_rewarm(monkeypatch):
    """429는 레이트리밋(쿠키는 유효) — 냉각으로 풀리므로 재워밍업 불필요."""
    _, warm_calls = _patch_warmup(monkeypatch, statuses=[200, 429, 200])
    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId={}"
    c._http_get(url.format(1))
    c._http_get(url.format(2))
    c._http_get(url.format(3))
    assert len(warm_calls) == 1


# --- 프록시 경유 (선택) ---
# 데이터센터 IP는 Akamai가 위험군으로 분류할 수 있다. 환경변수 SSG_PROXY가
# 설정되면 브라우저 워밍업과 HTTP 수집 모두 해당 프록시를 경유한다
# (미설정이면 기존과 동일하게 직접 요청).

def test_no_proxy_by_default(monkeypatch):
    monkeypatch.delenv("SSG_PROXY", raising=False)
    assert SSGCrawler._proxy() is None
    assert SSGCrawler._warmup_session_kwargs() == {
        "headless": False,
        "timeout": SSGCrawler.WARMUP_TIMEOUT_MS,
        "retries": 1,
    }


def test_proxy_applied_to_warmup_and_http(monkeypatch):
    import curl_cffi.requests as curl_requests

    monkeypatch.setenv("SSG_PROXY", "http://user:pw@proxy.example:8080")
    monkeypatch.setattr(SSGCrawler, "_http_session", None)

    assert SSGCrawler._proxy() == "http://user:pw@proxy.example:8080"
    assert SSGCrawler._warmup_session_kwargs()["proxy"] == (
        "http://user:pw@proxy.example:8080"
    )

    created = {}

    class _FakeSession:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.cookies = _FakeCookieJar()

    monkeypatch.setattr(curl_requests, "Session", _FakeSession)
    SSGCrawler._get_http_session()
    assert created["proxies"] == {
        "http": "http://user:pw@proxy.example:8080",
        "https": "http://user:pw@proxy.example:8080",
    }


# --- Camoufox 워밍업 (지문 위장) ---
# 2026-08-01 실측: 서버는 GPU가 없어 WebGL이 소프트웨어 렌더러(llvmpipe)로
# 노출되고, 이 지문 때문에 한국 주거용 프록시 IP로 나가도 SSG 상품 페이지가
# 403이다. Camoufox(지문을 네이티브로 위장하는 Firefox)로 워밍업하면
# 실제 PC 지문으로 보인다. Camoufox는 Firefox이므로 이후 HTTP 재생도
# Firefox로 위장해야 쿠키가 유효하다.

def test_warmup_prefers_camoufox_when_available(monkeypatch):
    monkeypatch.setattr(SSGCrawler, "_camoufox_available", classmethod(lambda cls: True))
    assert SSGCrawler._warm_impersonate() == "firefox"


def test_warmup_falls_back_to_chrome_impersonation(monkeypatch):
    monkeypatch.setattr(SSGCrawler, "_camoufox_available", classmethod(lambda cls: False))
    assert SSGCrawler._warm_impersonate() == "chrome"


def test_camoufox_options_spoof_desktop_fingerprint(monkeypatch):
    monkeypatch.delenv("SSG_PROXY", raising=False)
    opts = SSGCrawler._camoufox_options()
    assert opts["os"] == "windows"          # 리눅스 서버 흔적 제거
    assert opts["headless"] is True         # Xvfb 없이도 동작해야 한다
    # humanize는 headless에서 무한 대기 사례가 있어 끈다 — 사람 흔적은
    # _browse_for_cookies의 명시적 마우스/스크롤로 공급한다
    assert opts["humanize"] is False
    assert opts["locale"] == "ko-KR"
    assert opts["webgl_config"]             # llvmpipe 대신 실제 GPU 문자열
    assert "proxy" not in opts


def test_camoufox_options_include_proxy(monkeypatch):
    monkeypatch.setenv("SSG_PROXY", "http://u:p@gw.example:823")
    opts = SSGCrawler._camoufox_options()
    assert opts["proxy"] == {
        "server": "http://gw.example:823",
        "username": "u",
        "password": "p",
    }


def test_warm_cookies_applied_with_declared_impersonation(monkeypatch):
    import curl_cffi.requests as curl_requests

    created = {}

    class _FakeSession:
        def __init__(self, **kwargs):
            created.update(kwargs)
            self.cookies = _FakeCookieJar()

    monkeypatch.setattr(curl_requests, "Session", _FakeSession)
    monkeypatch.setattr(SSGCrawler, "_http_session", None)
    SSGCrawler._apply_warm_cookies(
        {
            "cookies": [{"name": "_abck", "value": "v", "domain": ".ssg.com"}],
            "ua": "Mozilla/5.0 (Windows NT 10.0; rv:133.0) Gecko/20100101 Firefox/133.0",
            "impersonate": "firefox",
        }
    )
    assert created["impersonate"] == "firefox"
    assert "Firefox" in SSGCrawler._warm_ua


# --- 서킷 브레이커 완화 ---
# 2026-08-01 실측: 워밍업 3회 실패로 30분 차단이 걸려 잡의 74%(656건)가
# 통째로 스킵됐다. 잡 길이가 ~45분이라 30분 차단은 사실상 잡 포기와 같다.
# 차단을 짧게(5분) 잡고, 만료 시 실패 카운터를 리셋해 다시 기회를 준다.

def test_block_duration_shorter_than_typical_job():
    assert SSGCrawler.BLOCK_FAST_FAIL_DURATION <= 600


def test_failure_counter_resets_after_block_expires(monkeypatch):
    """차단이 풀린 뒤에는 한 번 더 실패해도 곧바로 재차단되면 안 된다
    (누적 카운터가 남아 있으면 실패 1회에 30분씩 반복 차단됨)."""
    import time

    monkeypatch.setattr(SSGCrawler, "MAX_WARMUP_FAILURES", 2)
    monkeypatch.setattr(SSGCrawler, "BLOCK_FAST_FAIL_DURATION", 0.2)
    _, warm_calls = _patch_warmup(
        monkeypatch, statuses=[], warm_results=[False, False, False, True]
    )

    c = SSGCrawler()
    url = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1"
    c._http_get(url)                      # 실패 1
    c._http_get(url)                      # 실패 2 → 차단
    assert SSGCrawler._fast_fail_until > 0

    time.sleep(0.25)                      # 차단 만료
    c._http_get(url)                      # 실패 3 — 카운터가 리셋됐다면 재차단 안 됨
    assert not SSGCrawler._is_blocked()
    assert c._http_get(url) is not None    # 이어서 성공
    assert len(warm_calls) == 4
