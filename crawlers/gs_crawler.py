"""GS Shop 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict
import re


class GSCrawler(BaseCrawler):
    """GS Shop 크롤러 (JavaScript 동적 로딩으로 Selenium 필수)"""

    def __init__(self):
        super().__init__(use_selenium=True)  # GS는 Selenium 필요

    def extract_price(self, html: str, url: str) -> Dict:
        """GS Shop 가격 정보 추출 (기존 JS 로직 참고)"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        # 가격 선택자 (우선순위대로)
        price_selectors = [
            ".price-definition-ins ins strong",
            "#totValue",
            "em#totValue",
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

                # "원" 기준으로 split 해서 첫 번째 부분만 사용 (추가 배송비 제외)
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
        """타임스탬프 생성"""
        from datetime import datetime

        return datetime.now().isoformat()
