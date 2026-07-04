"""롯데 아이몰 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class LotteCrawler(BaseCrawler):
    """롯데 아이몰 크롤러 (HTTP 방식)"""

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return []

    def extract_price(self, html: str, url: str) -> Dict:
        """롯데 아이몰 가격 정보 추출"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        logger.info(f"[롯데] URL: {url[:60]}...")
        logger.info(f"[롯데] HTML 길이: {len(html)}")

        price_selectors = [
            ".price_product .final .num",
            ".price_product .price .final .num",
            ".final_price_area .heading .price .num",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            for elem in elems:
                price_text = re.sub(r"[^\d]", "", elem.get_text())
                price = int(price_text) if price_text else None
                if price and price > 100:
                    price_elem = elem
                    product_price = price
                    logger.info(f"[롯데] ✅ 가격 발견: {product_price}원 (선택자: {selector})")
                    break
            if price_elem:
                break

        if product_price is None:
            logger.warning(f"[롯데] ❌ 가격을 찾지 못함")

        delivery_selectors = [
            ".row_product.delivery .cont > p:first-of-type",
            ".row_product.delivery .cont p",
            ".delivery .cont p",
        ]
        for selector in delivery_selectors:
            delivery_elem = soup.select_one(selector)
            if delivery_elem:
                text = delivery_elem.get_text()
                if "배송비" in text and "추가" not in text:
                    first_part = text.split("원")[0]
                    delivery_text = re.sub(r"[^\d]", "", first_part)
                    delivery_price = int(delivery_text) if delivery_text else 0
                    delivery_status = "유료" if delivery_price > 0 else "무료"
                    break

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
