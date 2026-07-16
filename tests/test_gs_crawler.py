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


# 실사이트에서 배송비 표시는 JS가 페이지 내 JSON(dlvTxt)을 읽어 그리므로
# 정적 HTML에는 CSS 선택자로 잡히는 배송비 요소가 없다. JSON fallback이
# 배송비를 뽑아야 한다. (2026-07 실페이지 dlvTxt 문구 그대로 사용)
HTML_DELIVERY_IN_JSON = """
<html><body>
<em id="totValue">40,000</em>
<script>var prdData = {"dlvInfoGrp":{"dlvTxt":"1000만원 이상 무료배송 (1000만원 미만 배송비 2,500원)"}};</script>
</body></html>
"""

HTML_DELIVERY_FREE_IN_JSON = """
<html><body>
<em id="totValue">40,000</em>
<script>var prdData = {"dlvInfoGrp":{"dlvTxt":"무료배송"}};</script>
</body></html>
"""


def test_delivery_from_embedded_json():
    r = GSCrawler().extract_price(HTML_DELIVERY_IN_JSON, "http://t")
    assert r["배송비"] == 2500
    assert r["배송비 여부"] == "유료"
    assert r["최종 가격"] == 42500


def test_delivery_free_from_embedded_json():
    r = GSCrawler().extract_price(HTML_DELIVERY_FREE_IN_JSON, "http://t")
    assert r["배송비"] == 0
    assert r["배송비 여부"] == "무료"


# 또 다른 실페이지 문구: "배송비 N원"이 아니라 "유료배송 <strong>N</strong>원"
# 꼴 (JSON 문자열 안에 HTML 태그 포함)
HTML_DELIVERY_PAID_TAGGED_JSON = """
<html><body>
<em id="totValue">125,400</em>
<script>var prdData = {"dlvInfoGrp":{"dlvTxt":"유료배송 <strong>2,500</strong>원"}};</script>
</body></html>
"""


def test_delivery_paid_tagged_from_embedded_json():
    r = GSCrawler().extract_price(HTML_DELIVERY_PAID_TAGGED_JSON, "http://t")
    assert r["배송비"] == 2500
    assert r["배송비 여부"] == "유료"


def test_delivery_css_selector_keeps_priority():
    """CSS 선택자로 배송비가 잡히면 JSON fallback보다 우선한다."""
    html = """
    <html><body>
    <em id="totValue">40,000</em>
    <p class="shipCate"><strong>3,000원</strong></p>
    <script>var prdData = {"dlvTxt":"1000만원 이상 무료배송 (1000만원 미만 배송비 2,500원)"};</script>
    </body></html>
    """
    r = GSCrawler().extract_price(html, "http://t")
    assert r["배송비"] == 3000
