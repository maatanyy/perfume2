"""CJ 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class CJCrawler(BaseCrawler):
    """CJ온스타일 크롤러 (Selenium) - 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".item_price strong.ff_price",
        ".opt_area .item_price strong.ff_price",
        ".price_bx .txt_price .ff_price",
        ".txt_price .ff_price",
        ".total_price_wrap strong.ff_price",
        ".price_area .price_txt > strong.ff_price",
        ".ff_price",
    ]
    # 실사이트에서 쿠폰가 노출 사례로 미검증 (2026-07 검증 시 쿠폰 미노출/403)
    # — 쿠폰가 오탐 시 이 선택자부터 의심할 것.
    COUPON_PRICE_SELECTORS = [
        ".coupon_price .ff_price",
        ".price_coupon .ff_price",
        ".benefit_price .ff_price",
    ]
    DELIVERY_SELECTORS = [
        ".gift_delivery_wrap .delivery_fees strong",
        ".delivery_fees strong",
    ]
    SOLD_OUT_SELECTORS = [
        ".btn_soldout",
        ".soldout_layer .txt",
    ]

    def __init__(self):
        super().__init__(use_selenium=True)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            ".item_price strong.ff_price",
            ".ff_price",
            ".txt_price .ff_price",
            ".total_price_wrap strong.ff_price",
        ]

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                digits = re.sub(r"[^\d]", "", elem.get_text())
                delivery_price = int(digits) if digits else 0
                return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[CJ] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[CJ] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[CJ] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[CJ] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
