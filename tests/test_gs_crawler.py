"""GS샵 크롤러 테스트"""

from crawlers.gs_crawler import GSCrawler

HTML_SALE_AND_COUPON = """
<html><body>
<div class="price-definition-ins"><ins><strong>50,000</strong></ins></div>
<div class="price-definition-coupon"><strong>45,000</strong></div>
<p class="shipCate"><strong>2,500원</strong></p>
</body></html>
"""

HTML_SALE_ONLY = """
<html><body>
<em id="totValue">50,000</em>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><div class="prd-btn-soldout">일시품절</div></body></html>
"""


def test_sale_and_coupon_split():
    r = GSCrawler().extract_price(HTML_SALE_AND_COUPON, "http://t")
    assert r["판매가"] == 50000
    assert r["쿠폰적용가"] == 45000
    assert r["배송비"] == 2500
    assert r["최종 가격"] == 47500
    assert r["결과 상태"] == "success"


def test_sale_only_has_status_key():
    r = GSCrawler().extract_price(HTML_SALE_ONLY, "http://t")
    assert r["판매가"] == 50000
    assert r["결과 상태"] == "success"   # 기존 버그: 이 키가 없었음


def test_sold_out():
    r = GSCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
