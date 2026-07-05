"""신세계TV쇼핑 크롤러 테스트 (HTML 픽스처 기반)"""

from crawlers.shinsegae_crawler import ShinsegaeCrawler

HTML_SALE_AND_BEST = """
<html><body>
<div class="price--3">
  <span class="_salePrice">45,000</span>
  <span class="_bestPrice">40,500</span>
</div>
</body></html>
"""

HTML_BEST_ONLY = """
<html><body>
<div class="div-best"><span class="_bestPrice">40,500</span></div>
</body></html>
"""

HTML_SOLD_OUT = """
<html><body>
<div class="prd-detail"><span class="badge-soldout">일시품절</span></div>
</body></html>
"""

HTML_EMPTY = "<html><body><p>내용 없음</p></body></html>"


def test_sale_and_coupon_split():
    r = ShinsegaeCrawler().extract_price(HTML_SALE_AND_BEST, "http://t")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] == 40500
    assert r["상품 가격"] == 40500
    assert r["결과 상태"] == "success"


def test_best_price_only():
    r = ShinsegaeCrawler().extract_price(HTML_BEST_ONLY, "http://t")
    assert r["판매가"] is None
    assert r["쿠폰적용가"] == 40500
    assert r["상품 가격"] == 40500
    assert r["결과 상태"] == "success"


def test_sold_out_detected():
    r = ShinsegaeCrawler().extract_price(HTML_SOLD_OUT, "http://t")
    assert r["결과 상태"] == "sold_out"
    assert r["판매가"] is None


def test_not_found():
    r = ShinsegaeCrawler().extract_price(HTML_EMPTY, "http://t")
    assert r["결과 상태"] == "not_found"
