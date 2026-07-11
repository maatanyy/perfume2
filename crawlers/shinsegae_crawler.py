"""신세계 쇼핑 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List
import re
import logging

logger = logging.getLogger(__name__)


class ShinsegaeCrawler(BaseCrawler):
    """신세계TV쇼핑 크롤러 - HTTP 방식, 판매가/쿠폰적용가 분리"""

    # 판매가 (실사이트 검증: 상품 상세 페이지는 `<span class="blind">판매가</span>`
    # 바로 뒤에 `._bestPrice`가 실제 판매가로 렌더링됨 — `._salePrice`는 실사이트에
    # 존재하지 않았고, `.sale_price`(공백 없는 별개 클래스)는 할부/적립포인트 안내
    # 텍스트("300P" 등)를 가진 무관한 요소라 오탐(예: 판매가 300원 오추출)을 유발함)
    SALE_PRICE_SELECTORS = [
        ".div-best ._bestPrice",
        "._bestPrice",
        "._salePrice",
        ".price--3 ._salePrice",
    ]
    # 쿠폰/혜택 적용가 — 검증한 5개 상품 모두 페이지 내 사전 계산된 쿠폰적용가
    # 요소가 없었음(쿠폰은 "쿠폰 발급받기" 모달의 할인율(%)로만 노출, 최종가 미표시).
    # ._bestPrice는 위 판매가로 재분류했으므로 여기서는 제거 — 실제 쿠폰가 표시
    # 요소를 찾으면 아래에 추가할 것.
    COUPON_PRICE_SELECTORS: List[str] = []
    # 품절 표시 (실사이트 검증 태스크에서 보정)
    SOLD_OUT_SELECTORS = [
        ".badge-soldout",
        ".btn-soldout",
        "[class*='soldOut']",
    ]

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            "._bestPrice",
            "._salePrice",
            ".price--3 ._bestPrice",
            ".div-best ._bestPrice",
        ]

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[신세계] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[신세계] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[신세계] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        logger.info(f"[신세계] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}")
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=0, delivery_status="무료",
        )
