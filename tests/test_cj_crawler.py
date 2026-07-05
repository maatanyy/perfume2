"""CJ온스타일 크롤러 테스트"""

from crawlers.cj_crawler import CJCrawler

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
