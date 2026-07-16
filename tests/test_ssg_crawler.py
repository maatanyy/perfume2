"""SSG 크롤러 테스트"""

from crawlers.ssg_crawler import SSGCrawler

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


# --- www.ssg.com 봇 차단 빠른 실패 ---
# www.ssg.com은 Akamai가 상품 페이지를 상시 차단한다 (HTTP/headless 브라우저
# 모두 실측 차단 확인). www는 재시도 없이 명확한 오류로 즉시 기록하고,
# HTTP가 통과하는 서브도메인은 기존 재시도 경로를 유지해야 한다.

def test_www_http_failure_fails_fast_with_clear_error(monkeypatch):
    from crawlers.base_crawler import BaseCrawler

    calls = []

    def fake_fetch(self, url, wait_time=2):
        calls.append(url)
        return None

    monkeypatch.setattr(BaseCrawler, "fetch_page", fake_fetch)
    r = SSGCrawler().crawl_price("https://www.ssg.com/item/itemView.ssg?itemId=1")
    assert r["결과 상태"] == "error"
    assert "봇 차단" in r["에러 발생"]
    assert len(calls) == 1             # 재시도 없이 즉시 실패


def test_subdomain_http_failure_keeps_retry_path(monkeypatch):
    from crawlers.base_crawler import BaseCrawler

    calls = []

    def fake_fetch(self, url, wait_time=2):
        calls.append(url)
        return None

    monkeypatch.setattr(BaseCrawler, "fetch_page", fake_fetch)
    r = SSGCrawler().crawl_price(
        "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1", max_retries=1
    )
    assert r["결과 상태"] == "error"
    assert "봇 차단" not in r["에러 발생"]  # 일반 실패 메시지 유지


def test_www_http_success_extracts_normally(monkeypatch):
    from crawlers.base_crawler import BaseCrawler

    monkeypatch.setattr(
        BaseCrawler, "fetch_page", lambda self, url, wait_time=2: HTML_SALE_WITH_DELIVERY
    )
    r = SSGCrawler().crawl_price("https://www.ssg.com/item/itemView.ssg?itemId=1")
    assert r["결과 상태"] == "success"
    assert r["판매가"] == 45000
