"""롯데 아이몰 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class LotteCrawler(BaseCrawler):
    """롯데아이몰 크롤러 - HTTP 방식, 판매가/쿠폰적용가 분리"""

    # 실사이트 검증: 실제 DOM은
    #   <span class="origin"><span class="line">189,000</span> 원</span>
    #   <div class="price"><div class="percent">5%</div>
    #     <div class="final"><span class="num">179,550</span>원</div></div>
    # 구조라 `.origin .num`(존재하지 않음, 실제 클래스는 `.line`)은 매칭되지
    # 않았고, `.final .num`이 실제 판매가(할인 적용 표시가)였다. `.origin`은
    # 할인 전 정가라 판매가 대체값으로 쓰면 값이 부풀려지므로 fallback에서 제외.
    SALE_PRICE_SELECTORS = [
        ".price_product .final .num",
        ".price_product .sale .num",
        ".sale_prc",
    ]
    # 쿠폰적용가 — 검증한 상품들은 모두 쿠폰할인액이 페이지 내 JS 데이터
    # (discountList)에만 들어있고 사전 계산된 "쿠폰적용 후 최종가" DOM 요소가
    # 없었다(쿠폰 미다운로드 상태 기준). `.final .num`은 위에서 판매가로
    # 재분류했으므로 여기서는 제거 — 실제 쿠폰적용가 표시 요소를 찾으면 추가할 것.
    COUPON_PRICE_SELECTORS: List[str] = []
    DELIVERY_SELECTORS = [
        ".row_product.delivery .cont > p:first-of-type",
        ".row_product.delivery .cont p",
        ".delivery .cont p",
    ]
    SOLD_OUT_SELECTORS = [
        ".btn_soldout_area",
        ".soldout_wrap",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return []

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text()
                if "배송비" in text and "추가" not in text:
                    first_part = text.split("원")[0]
                    digits = re.sub(r"[^\d]", "", first_part)
                    delivery_price = int(digits) if digits else 0
                    return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[롯데] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[롯데] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[롯데] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[롯데] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
