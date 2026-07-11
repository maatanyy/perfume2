"""롯데아이몰 크롤러 테스트"""

from crawlers.lotte_crawler import LotteCrawler

HTML_SALE_AND_FINAL = """
<html><body>
<div class="price_product">
  <div class="sale"><span class="num">95,000</span></div>
  <div class="final"><span class="num">89,000</span></div>
</div>
<div class="row_product delivery"><div class="cont"><p>배송비 2,500원</p></div></div>
</body></html>
"""

HTML_FINAL_ONLY = """
<html><body>
<div class="price_product"><div class="final"><span class="num">89,000</span></div></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body><div class="btn_soldout_area">품절</div></body></html>
"""


def test_sale_and_coupon_split():
    r = LotteCrawler().extract_price(HTML_SALE_AND_FINAL, "http://t")
    assert r["판매가"] == 95000
    assert r["쿠폰적용가"] == 89000
    assert r["배송비"] == 2500
    assert r["최종 가격"] == 91500
    assert r["결과 상태"] == "success"


def test_final_only_becomes_representative():
    r = LotteCrawler().extract_price(HTML_FINAL_ONLY, "http://t")
    assert r["판매가"] is None
    assert r["쿠폰적용가"] == 89000
    assert r["상품 가격"] == 89000


def test_sold_out():
    r = LotteCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
