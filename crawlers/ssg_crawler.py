"""SSG 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict
import re


class SSGCrawler(BaseCrawler):
    """SSG 사이트 크롤러 (JavaScript 많아서 Selenium 필수)"""

    def __init__(self):
        super().__init__(use_selenium=True)  # SSG는 Selenium 필요

    def extract_price(self, html: str, url: str) -> Dict:
        """SSG 가격 정보 추출 (기존 JS 로직 참고)"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"
        is_ssg_shopping = False

        # SSG Shopping URL 체크 (더 정확한 감지)
        url_lower = url.lower()
        is_ssg_shopping = "shinsegaetvshopping.com" in url_lower or "ssg_shoping" in url_lower

        # 가격 선택자 (우선순위대로)
        price_selectors = [
            ".cdtl_new_price.notranslate .ssg_price",
            ".price--3",  # SSG Shopping
            ".price--3 ._salePrice",  # SSG Shopping sale price
            ".price--3 ._bestPrice",  # SSG Shopping best price
            ".cdtl_price .ssg_price",
            ".price_total .ssg_price",
            "em.ssg_price",
            ".special_price .ssg_price",
            # SSG Shopping 추가 선택자
            "._salePrice",
            "._bestPrice",
            ".div-best ._bestPrice",
            ".total_price .price em",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            if elems:
                # 여러 개가 있을 수 있으므로 100원 이상인 것만 선택
                for elem in elems:
                    price_text = re.sub(r"[^\d]", "", elem.get_text())
                    price = int(price_text) if price_text else None
                    
                    if price and price > 100:  # 100원 이상만 (할인율 제외)
                        price_elem = elem
                        # SSG Shopping 관련 선택자인지 확인
                        if not is_ssg_shopping:
                            is_ssg_shopping = ".price--3" in selector or "._salePrice" in selector or "._bestPrice" in selector or ".div-best" in selector
                        break
                
                if price_elem:
                    break

        # 가격 추출
        if price_elem:
            if is_ssg_shopping:
                # SSG Shopping의 경우 내부 요소에서 가격 찾기
                sale_price = price_elem.select_one("._salePrice")
                best_price = price_elem.select_one("._bestPrice")
                
                if sale_price:
                    price_text = sale_price.get_text()
                elif best_price:
                    price_text = best_price.get_text()
                else:
                    price_text = price_elem.get_text()
                
                cleaned = re.sub(r"[^\d]", "", price_text)
                product_price = int(cleaned) if cleaned and int(cleaned) > 100 else None
            else:
                price_text = price_elem.get_text()
                cleaned = re.sub(r"[^\d]", "", price_text)
                product_price = int(cleaned) if cleaned and int(cleaned) > 100 else None

        # 배송비 추출 (일반 SSG만)
        if not is_ssg_shopping:
            delivery_selectors = [
                ".cdtl_dl.cdtl_delivery_fee li em.ssg_price",
                ".delivery_fee .ssg_price",
                ".cdtl_delivery_fee em",
            ]

            for selector in delivery_selectors:
                delivery_elem = soup.select_one(selector)
                if delivery_elem:
                    numbers = re.sub(r"[^\d]", "", delivery_elem.get_text())
                    delivery_price = int(numbers) if numbers else 0
                    delivery_status = "유료" if delivery_price > 0 else "무료"
                    break
        else:
            delivery_status = "배송비가 없습니다"

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
