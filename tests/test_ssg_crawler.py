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
