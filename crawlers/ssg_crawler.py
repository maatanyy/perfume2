"""SSG 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class SSGCrawler(BaseCrawler):
    """SSG 사이트 크롤러 (JavaScript 많아서 Selenium 필수)"""

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        """가격 요소 동적 대기용 선택자"""
        return [
            ".cdtl_new_price.notranslate .ssg_price",
            ".price--3",
            "em.ssg_price",
            "._salePrice",
            "._bestPrice",
        ]

    def extract_price(self, html: str, url: str) -> Dict:
        """SSG 가격 정보 추출"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"
        is_ssg_shopping = False

        logger.info(f"[SSG] URL: {url[:60]}...")
        logger.info(f"[SSG] HTML 길이: {len(html)}")

        price_selectors = [
            ".cdtl_new_price.notranslate .ssg_price",
            ".price--3",
            ".price--3 ._salePrice",
            ".price--3 ._bestPrice",
            ".cdtl_price .ssg_price",
            ".price_total .ssg_price",
            "em.ssg_price",
            ".special_price .ssg_price",
            "._salePrice",
            "._bestPrice",
            ".div-best ._bestPrice",
            ".total_price .price em",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            if elems:
                logger.info(f"[SSG] 선택자 '{selector}': {len(elems)}개 발견")
                for elem in elems:
                    price_text = re.sub(r"[^\d]", "", elem.get_text())
                    price = int(price_text) if price_text else None
                    if price and price > 100:
                        price_elem = elem
                        logger.info(f"[SSG] ✅ 가격 발견: {price}원 (선택자: {selector})")
                        if not is_ssg_shopping:
                            is_ssg_shopping = (
                                ".price--3" in selector
                                or "._salePrice" in selector
                                or "._bestPrice" in selector
                                or ".div-best" in selector
                            )
                        break
                if price_elem:
                    break

        if price_elem:
            if is_ssg_shopping:
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

        total_price = (product_price + delivery_price) if product_price is not None else None

        if product_price:
            logger.info(f"[SSG] ✅ 최종 가격: {product_price}원, 배송비: {delivery_price}원")
        else:
            logger.warning(f"[SSG] ❌ 가격을 찾지 못함")

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
