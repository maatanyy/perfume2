"""BaseCrawler 공통 헬퍼 테스트"""

from bs4 import BeautifulSoup
from crawlers.base_crawler import BaseCrawler


class DummyCrawler(BaseCrawler):
    def __init__(self):
        super().__init__(use_selenium=False)

    def extract_price(self, html, url):
        return {}

    def get_sold_out_selectors(self):
        return [".my-soldout-badge"]


def make_soup(html):
    return BeautifulSoup(html, "lxml")


# ---------- parse_price ----------

def test_parse_price_extracts_digits():
    assert BaseCrawler.parse_price("45,000원") == 45000

def test_parse_price_rejects_small_numbers():
    # 100 이하는 퍼센트 등 오탐이므로 제외
    assert BaseCrawler.parse_price("10%") is None

def test_parse_price_empty_and_none():
    assert BaseCrawler.parse_price("") is None
    assert BaseCrawler.parse_price(None) is None


# ---------- select_first_price ----------

def test_select_first_price_priority_order():
    soup = make_soup(
        '<div><em class="second">9,900</em><em class="first">45,000</em></div>'
    )
    price = BaseCrawler.select_first_price(soup, [".first", ".second"])
    assert price == 45000

def test_select_first_price_no_match():
    soup = make_soup("<div><p>no price</p></div>")
    assert BaseCrawler.select_first_price(soup, [".first"]) is None


# ---------- build_price_result ----------

def test_build_result_with_coupon():
    c = DummyCrawler()
    r = c.build_price_result("http://x", sale_price=45000, coupon_price=40500,
                             delivery_price=2500, delivery_status="유료")
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] == 40500
    assert r["상품 가격"] == 40500          # 대표가 = 쿠폰가 우선
    assert r["최종 가격"] == 43000          # 쿠폰가 + 배송비
    assert r["결과 상태"] == "success"

def test_build_result_sale_only():
    c = DummyCrawler()
    r = c.build_price_result("http://x", sale_price=45000)
    assert r["판매가"] == 45000
    assert r["쿠폰적용가"] is None
    assert r["상품 가격"] == 45000
    assert r["최종 가격"] == 45000
    assert r["결과 상태"] == "success"

def test_build_result_coupon_not_cheaper_is_dropped():
    c = DummyCrawler()
    r = c.build_price_result("http://x", sale_price=40000, coupon_price=45000)
    assert r["쿠폰적용가"] is None
    assert r["상품 가격"] == 40000

def test_build_result_not_found_when_no_price():
    c = DummyCrawler()
    r = c.build_price_result("http://x")
    assert r["결과 상태"] == "not_found"
    assert r["최종 가격"] is None

def test_build_result_explicit_sold_out():
    c = DummyCrawler()
    r = c.build_price_result("http://x", status="sold_out",
                             delivery_price=None, delivery_status="매진/품절",
                             error="품절 감지")
    assert r["결과 상태"] == "sold_out"
    assert r["에러 발생"] == "품절 감지"
    assert r["판매가"] is None


# ---------- detect_sold_out ----------

def test_detect_sold_out_site_selector_presence():
    c = DummyCrawler()
    soup = make_soup('<div class="my-soldout-badge"></div>')
    assert c.detect_sold_out(soup) is True

def test_detect_sold_out_generic_requires_keyword():
    c = DummyCrawler()
    # 범용 선택자 매치되지만 품절 키워드 없음 → False (오탐 방지)
    soup = make_soup('<div class="soldout_layer">알림 신청</div>')
    assert c.detect_sold_out(soup) is False
    soup2 = make_soup('<div class="soldout_layer">일시품절</div>')
    assert c.detect_sold_out(soup2) is True

def test_detect_sold_out_clean_page():
    c = DummyCrawler()
    soup = make_soup("<div><p>정상 판매중 상품</p></div>")
    assert c.detect_sold_out(soup) is False
