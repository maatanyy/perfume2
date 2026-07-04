"""신세계 쇼핑 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class ShinsegaeCrawler(BaseCrawler):
    """신세계 쇼핑 크롤러 - Selenium 사용 (강화된 봇 우회)"""

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        """가격 요소 동적 대기용 선택자"""
        return [
            "._bestPrice",
            "._salePrice",
            ".price--3 ._bestPrice",
            ".div-best ._bestPrice",
        ]


    def extract_price(self, html: str, url: str) -> Dict:
        """신세계 쇼핑 가격 정보 추출"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        logger.info(f"[신세계] extract_price URL: {url[:60]}...")
        logger.info(f"[신세계] HTML 길이: {len(html)}")

        price_selectors = [
            "._bestPrice",
            ".price--3 ._bestPrice",
            "._salePrice",
            ".div-best ._bestPrice",
            ".total_price .price em",
            ".sale_price",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            if elems:
                logger.info(f"[신세계] 선택자 '{selector}': {len(elems)}개 발견")
            for elem in elems:
                price_text = re.sub(r"[^\d]", "", elem.get_text())
                price = int(price_text) if price_text else None
                if price and price > 100:
                    price_elem = elem
                    product_price = price
                    logger.info(f"[신세계] ✅ 가격 발견: {product_price}원")
                    break
            if price_elem:
                break

        if product_price is None:
            logger.warning(f"[신세계] ❌ 가격을 찾지 못함")

        total_price = (product_price + delivery_price) if product_price is not None else None

        return {
            "상품 url": url,
            "상품 가격": product_price,
            "배송비": delivery_price,
            "배송비 여부": delivery_status,
            "최종 가격": total_price,
            "결과 상태": "success" if product_price else "not_found",
            "추출 날짜": self._get_timestamp(),
        }

    def _get_timestamp(self):
        from datetime import datetime
        return datetime.now().isoformat()
