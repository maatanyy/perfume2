"""CJ 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class CJCrawler(BaseCrawler):
    """CJ 온스타일 크롤러 (JavaScript 동적 로딩으로 Selenium 사용)"""

    def __init__(self):
        super().__init__(use_selenium=True)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        """가격 요소 동적 대기용 선택자"""
        return [
            ".item_price strong.ff_price",
            ".ff_price",
            ".txt_price .ff_price",
            ".total_price_wrap strong.ff_price",
        ]

    def extract_price(self, html: str, url: str) -> Dict:
        """CJ 가격 정보 추출"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        logger.info(f"[CJ] URL: {url[:60]}...")
        logger.info(f"[CJ] HTML 길이: {len(html)}")

        price_selectors = [
            ".item_price strong.ff_price",
            ".opt_area .item_price strong.ff_price",
            ".price_bx .txt_price .ff_price",
            ".txt_price .ff_price",
            ".total_price_wrap strong.ff_price",
            ".ff_price",
            ".price_area .price_txt > strong.ff_price",
            ".price_area span:not(.txt_sale):not(.txt_del) > strong.ff_price",
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
                    logger.info(f"[CJ] ✅ 가격 발견: {product_price}원 (선택자: {selector})")
                    break
            if price_elem:
                break

        if product_price is None:
            logger.warning(f"[CJ] ❌ 가격을 찾지 못함")

        delivery_selectors = [
            ".gift_delivery_wrap .delivery_fees strong",
            ".delivery_fees strong",
        ]
        for selector in delivery_selectors:
            delivery_elem = soup.select_one(selector)
            if delivery_elem:
                delivery_text = re.sub(r"[^\d]", "", delivery_elem.get_text())
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
