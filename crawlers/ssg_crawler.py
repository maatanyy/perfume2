"""SSG 크롤러"""

from crawlers.base_crawler import BaseCrawler, SkipRetryError
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
import re
import logging

logger = logging.getLogger(__name__)


class SSGCrawler(BaseCrawler):
    """SSG.COM 크롤러 - 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".cdtl_new_price.notranslate .ssg_price",
        ".cdtl_price .ssg_price",
        ".price_total .ssg_price",
        "em.ssg_price",
        ".special_price .ssg_price",
        # 신세계TV 계열 URL fallback 대비 (컨테이너가 아닌 leaf 선택자만 사용
        # — 컨테이너 get_text()는 여러 가격을 이어붙인 값이 됨)
        "._salePrice",
        ".total_price .price em",
    ]
    # 실사이트에서 쿠폰가 노출 사례로 미검증 (2026-07 검증 시 쿠폰 미노출/403)
    # — 쿠폰가 오탐 시 이 선택자부터 의심할 것.
    COUPON_PRICE_SELECTORS = [
        ".cdtl_bene_price .ssg_price",
        ".cdtl_row_bene .ssg_price",
        "[class*='benefit'] .ssg_price",
    ]
    DELIVERY_SELECTORS = [
        ".cdtl_dl.cdtl_delivery_fee li em.ssg_price",
        ".delivery_fee .ssg_price",
        ".cdtl_delivery_fee em",
    ]
    # bare 'em.ssg_price' fallback 탐색 시 제외할 컨테이너.
    # COUPON_PRICE_SELECTORS / DELIVERY_SELECTORS와 동일한 영역의 컨테이너
    # 클래스만 모아둔 것 — 쿠폰가/배송비 영역에도 em.ssg_price가 있어
    # bare fallback이 이를 판매가로 오인하는 것을 방지한다.
    EXCLUDED_BARE_PRICE_CONTAINERS = [
        ".cdtl_bene_price",
        ".cdtl_row_bene",
        "[class*='benefit']",
        ".cdtl_dl.cdtl_delivery_fee",
        ".delivery_fee",
        ".cdtl_delivery_fee",
    ]
    SOLD_OUT_SELECTORS = [
        ".cdtl_btn_soldout",
        ".btn_soldout",
        ".cdtl_soldout",
    ]

    # www.ssg.com(본몰)은 Akamai Bot Manager가 상품 페이지를 상시 차단한다.
    # 2026-07 실측: 파이썬 HTTP(403), 일반 Selenium headless(차단 페이지),
    # undetected-chromedriver headless + 홈 워밍업(홈은 통과, 상품 페이지 차단)
    # 모두 실패. HTTP가 통과하는 서브도메인(shinsegaemall/department)은 정상
    # 수집되므로, www만 재시도 없이 명확한 오류로 즉시 기록한다.
    BLOCKED_HOST = "www.ssg.com"
    BLOCKED_HOST_ERROR = (
        "SSG 본몰(www.ssg.com) 봇 차단(Akamai) — 자동 수집 불가, 브라우저에서 직접 확인 필요"
    )

    def __init__(self):
        super().__init__(use_selenium=False)

    def fetch_page(self, url: str, wait_time: int = 2) -> Optional[str]:
        html = super().fetch_page(url, wait_time)
        if html is None and self.BLOCKED_HOST in url.lower():
            raise SkipRetryError(self.BLOCKED_HOST_ERROR)
        return html

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            ".cdtl_new_price.notranslate .ssg_price",
            ".price--3",
            "em.ssg_price",
            "._salePrice",
            "._bestPrice",
        ]

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    def _select_bare_ssg_price(self, soup):
        """bare 'em.ssg_price' fallback: 쿠폰/배송비 컨테이너 내부 요소는
        건너뛰고, 살아남은 첫 파싱 가능한 가격을 반환한다."""
        # id() 기반 동일성 비교: BS4의 == 는 마크업 동등성이라
        # 제외 컨테이너 밖의 동일 마크업 요소까지 건너뛰게 된다
        excluded_ids = set()
        for container_selector in self.EXCLUDED_BARE_PRICE_CONTAINERS:
            try:
                for container in soup.select(container_selector):
                    excluded_ids.update(id(d) for d in container.descendants)
            except Exception:
                continue
        for elem in soup.select("em.ssg_price"):
            if id(elem) in excluded_ids:
                continue
            price = self.parse_price(elem.get_text())
            if price is not None:
                return price
        return None

    def _select_sale_price(self, soup):
        """SALE_PRICE_SELECTORS를 순서대로 시도.
        마지막 bare 'em.ssg_price' fallback만 쿠폰/배송비 컨테이너를
        제외하고 탐색한다 (다른 선택자들의 우선순위는 그대로 유지)."""
        for selector in self.SALE_PRICE_SELECTORS:
            if selector == "em.ssg_price":
                price = self._select_bare_ssg_price(soup)
            else:
                price = self.select_first_price(soup, [selector])
            if price is not None:
                return price
        return None

    def _extract_delivery(self, soup):
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                digits = re.sub(r"[^\d]", "", elem.get_text())
                delivery_price = int(digits) if digits else 0
                return delivery_price, ("유료" if delivery_price > 0 else "무료")
        return 0, "무료"

    def extract_price(self, html: str, url: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        logger.info(f"[SSG] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self._select_sale_price(soup)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[SSG] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            logger.warning("[SSG] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[SSG] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
