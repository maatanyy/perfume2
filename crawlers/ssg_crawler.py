"""SSG 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class SSGCrawler(BaseCrawler):
    """SSG.COM 크롤러 - 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".cdtl_new_price.notranslate .ssg_price",
        ".cdtl_price .ssg_price",
        ".price_total .ssg_price",
        "em.ssg_price",
        ".special_price .ssg_price",
        # 신세계TV 계열 URL이 fallback으로 들어올 때 대비
        ".price--3",
        "._salePrice",
        ".total_price .price em",
    ]
    COUPON_PRICE_SELECTORS = [
        ".cdtl_bene_price .ssg_price",
        ".cdtl_row_bene .ssg_price",
        "[class*='benefit'] .ssg_price",
    ]
    DELIVERY_SELECTORS = [
        ".cdtl_dl.cdtl_delivery_fee li em.ssg_price",
        ".delivery_fee .ssg_price",
        ".cdtl_delivery_fee em",
        ".cdtl_delivery_fee ~ li em.ssg_price",
    ]
    SOLD_OUT_SELECTORS = [
        ".cdtl_btn_soldout",
        ".btn_soldout",
        ".cdtl_soldout",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            ".cdtl_new_price.notranslate .ssg_price",
            ".price--3",
            "em.ssg_price",
            "._salePrice",
            "._bestPrice",
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
        logger.info(f"[SSG] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[SSG] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[SSG] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[SSG] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
