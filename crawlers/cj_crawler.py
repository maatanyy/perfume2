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

        # 디버깅: HTML 길이 및 샘플 출력
        print(f"[CJ DEBUG] HTML 길이: {len(html)}")
        print(f"[CJ DEBUG] URL: {url}")

        # ff_price 요소가 있는지 전체 검색
        all_ff_price = soup.select(".ff_price")
        print(f"[CJ DEBUG] 전체 .ff_price 요소 수: {len(all_ff_price)}")
        for i, elem in enumerate(all_ff_price[:5]):  # 처음 5개만 출력
            text = elem.get_text().strip()
            print(
                f"[CJ DEBUG] .ff_price[{i}]: '{text}' | 부모: {elem.parent.name if elem.parent else 'None'}"
            )

        # 가격 선택자 (우선순위대로) - 2026년 1월 CJ 온스타일 구조에 맞게 업데이트
        price_selectors = [
            # 최신 CJ 온스타일 선택자
            ".item_price strong.ff_price",
            ".opt_area .item_price strong.ff_price",
            ".price_bx .txt_price .ff_price",
            ".txt_price .ff_price",
            ".total_price_wrap strong.ff_price",
            # 기존 선택자 (백업)
            ".price_area .price_txt > strong.ff_price",
            ".price_area span:not(.txt_sale):not(.txt_del) > strong.ff_price",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            print(f"[CJ DEBUG] 선택자 '{selector}': {len(elems)}개 발견")
            for elem in elems:
                price_text = re.sub(r"[^\d]", "", elem.get_text())
                price = int(price_text) if price_text else None

                if price and price > 100:  # 100원 이상만 (할인율 제외)
                    price_elem = elem
                    product_price = price
                    print(f"[CJ DEBUG] ✅ 가격 발견: {product_price}원")
                    break

            if price_elem:
                break

        if product_price is None:
            print(f"[CJ DEBUG] ❌ 가격을 찾지 못함")

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
