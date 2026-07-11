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
