"""CJ 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict
import re


class CJCrawler(BaseCrawler):
    """CJ 온스타일 크롤러 (JavaScript 동적 로딩으로 Selenium 권장)"""

    def __init__(self):
        super().__init__(use_selenium=True)  # CJ는 Selenium 필요

    def extract_price(self, html: str, url: str) -> Dict:
        """CJ 가격 정보 추출 (기존 JS 로직 참고)"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        # 가격 선택자 (우선순위대로)
        price_selectors = [
            ".price_area .price_txt > strong.ff_price",
            ".price_area span:not(.txt_sale):not(.txt_del) > strong.ff_price",
            ".opt_area .item_price strong.ff_price",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            for elem in elems:
                price_text = re.sub(r"[^\d]", "", elem.get_text())
                price = int(price_text) if price_text else None

                if price and price > 100:  # 100원 이상만 (할인율 제외)
                    price_elem = elem
                    product_price = price
                    break

            if price_elem:
                break

        # 배송비 추출
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
        """타임스탬프 생성"""
        from datetime import datetime

        return datetime.now().isoformat()
