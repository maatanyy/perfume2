"""신세계 쇼핑 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict
import re


class ShinsegaeCrawler(BaseCrawler):
    """신세계 쇼핑 크롤러 - Selenium 사용 (HTTP 차단됨)"""

    def __init__(self):
        # 서버에서 HTTP 요청이 차단되어 Selenium 사용
        super().__init__(use_selenium=True)

    def extract_price(self, html: str, url: str) -> Dict:
        """신세계 쇼핑 가격 정보 추출"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        # 디버깅 로그
        print(f"[신세계 DEBUG] URL: {url}")
        print(f"[신세계 DEBUG] HTML 길이: {len(html)}")

        # 가격 선택자 (우선순위대로) - 2026년 1월 업데이트
        price_selectors = [
            "._bestPrice",  # 할인가 (우선)
            ".price--3 ._bestPrice",
            "._salePrice",  # 정가
            ".div-best ._bestPrice",
            ".total_price .price em",
            ".sale_price",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            if elems:
                print(f"[신세계 DEBUG] 선택자 '{selector}': {len(elems)}개 발견")

            for elem in elems:
                # 텍스트에서 숫자만 추출 (콤마 제거)
                price_text = re.sub(r"[^\d]", "", elem.get_text())
                price = int(price_text) if price_text else None

                if price and price > 100:  # 100원 이상만 (할인율 제외)
                    price_elem = elem
                    product_price = price
                    print(f"[신세계 DEBUG] ✅ 가격 발견: {product_price}원")
                    break

            if price_elem:
                break

        if product_price is None:
            print(f"[신세계 DEBUG] ❌ 가격을 찾지 못함")

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
