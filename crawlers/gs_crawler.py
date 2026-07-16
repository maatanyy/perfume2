"""GS Shop 크롤러 - HTTP 방식 (Selenium 불필요)"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class GSCrawler(BaseCrawler):
    """GS샵 크롤러 - HTTP 방식, 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".price-definition-ins ins strong",
        "#totValue",
        "em#totValue",
        ".item_price strong",
        ".price_value strong",
        ".sale_price strong",
    ]
    # 실사이트에서 쿠폰가 노출 사례로 미검증 (2026-07 검증 시 쿠폰 미노출)
    # — 쿠폰가 오탐 시 이 선택자부터 의심할 것.
    COUPON_PRICE_SELECTORS = [
        ".price-definition-coupon strong",
        ".coupon-price strong",
    ]
    DELIVERY_SELECTORS = [
        ".shipCate strong",
        "p.shipCate strong",
        ".paragraph1 .shipCate strong",
    ]
    SOLD_OUT_SELECTORS = [
        ".prd-btn-soldout",
        ".btn-soldout",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return []  # HTTP 방식 - 불필요

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                first_part = elem.get_text().split("원")[0]
                digits = re.sub(r"[^\d]", "", first_part)
                delivery_price = int(digits) if digits else 0
                return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[GS] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[GS] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[GS] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[GS] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
