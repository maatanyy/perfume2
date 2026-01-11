"""신세계 쇼핑 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict
import re


class ShinsegaeCrawler(BaseCrawler):
    """신세계 쇼핑 크롤러 (JavaScript 동적 로딩으로 Selenium 권장)"""

    def __init__(self):
        super().__init__(use_selenium=True)  # 신세계는 Selenium 필요

    def extract_price(self, html: str, url: str) -> Dict:
        """신세계 쇼핑 가격 정보 추출 (기존 JS 로직 참고)"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        # 가격 선택자 (우선순위대로)
        price_selectors = [
            ".div-best ._bestPrice",
            ".total_price .price em",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)

            # 여러 개가 있을 수 있으므로 100원 이상인 것만 선택
            for elem in elems:
                price_text = re.sub(r"[^\d]", "", elem.get_text())
                price = int(price_text) if price_text else None

                if price and price > 100:  # 100원 이상만 (할인율 제외)
                    price_elem = elem
                    product_price = price
                    break

            if price_elem:
                break

        # 배송비는 기존 코드에서 주석 처리되어 있음 (추후 필요시 추가)
        # delivery_selectors = [
        #     # 신세계 쇼핑 배송비
        # ]

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
