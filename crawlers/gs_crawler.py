"""GS Shop 크롤러 - HTTP 방식 (Selenium 불필요)"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class GSCrawler(BaseCrawler):
    """GS Shop 크롤러 - HTTP 요청 방식 (JavaScript 불필요)"""

    def __init__(self):
        super().__init__(use_selenium=False)  # HTTP 요청으로 충분

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return []  # HTTP 방식 - 불필요

    def extract_price(self, html: str, url: str) -> Dict:
        """GS Shop 가격 정보 추출"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        logger.info(f"[GS] URL: {url[:60]}...")
        logger.info(f"[GS] HTML 길이: {len(html)}")

        # 가격 선택자 (우선순위대로)
        price_selectors = [
            ".price-definition-ins ins strong",
            "#totValue",
            "em#totValue",
            ".item_price strong",
            ".price_value strong",
            ".sale_price strong",
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
                    logger.info(f"[GS] ✅ 가격 발견: {product_price}원 (선택자: {selector})")
                    break
            if price_elem:
                break

        if product_price is None:
            logger.warning(f"[GS] ❌ 가격을 찾지 못함")

        # 배송비 추출
        delivery_selectors = [
            ".shipCate strong",
            "p.shipCate strong",
            ".paragraph1 .shipCate strong",
        ]

        for selector in delivery_selectors:
            delivery_elem = soup.select_one(selector)
            if delivery_elem:
                text = delivery_elem.get_text()
                first_part = text.split("원")[0]
                delivery_text = re.sub(r"[^\d]", "", first_part)
                delivery_price = int(delivery_text) if delivery_text else 0
                delivery_status = "유료" if delivery_price > 0 else "무료"
                break

        total_price = (
            (product_price + delivery_price) if product_price is not None else None
        )

        return {
            "상품 url": url,
            "상품 가격": product_price,
            "배송비": delivery_price,
            "배송비 여부": delivery_status,
            "최종 가격": total_price,
            "추출 날짜": self._get_timestamp(),
        }

    def _get_timestamp(self):
        from datetime import datetime
        return datetime.now().isoformat()
