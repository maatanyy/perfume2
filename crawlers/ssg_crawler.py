"""SSG 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit
import re
import logging
import threading
import time

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

    # www.ssg.com(본몰)·ssg.com·emart.ssg.com은 Akamai Bot Manager가 상품
    # 페이지를 상시 차단한다 (2026-07 실측: HTTP 403, headless 브라우저 차단).
    # 같은 itemId를 shinsegaemall.ssg.com으로 열면 차단 없이 열리고 가격도
    # 동일함을 실측 확인 → 차단 도메인은 서브도메인으로 재작성해 HTTP 수집.
    # 재작성 후에도 실패하면(레이트리밋 추정) 냉각 후 crawl_price 재시도를
    # 타고, 최종 실패 시 명확한 오류로 기록한다.
    BLOCKED_HOSTS = {"www.ssg.com", "ssg.com", "emart.ssg.com"}
    REWRITE_HOST = "shinsegaemall.ssg.com"
    REWRITE_FAIL_ERROR = (
        "SSG 요청 실패(레이트리밋/봇 차단 추정) — shinsegaemall 우회 요청도 실패, 잠시 후 재실행 필요"
    )

    # shinsegaemall도 짧은 시간에 요청이 몰리면 일시 차단(429)된다 (2026-07
    # 실측: 0.7초 간격 연속 요청 시 ~17건 후 차단). 롯데와 같은 방식으로
    # 클래스 전역 최소 요청 간격을 강제한다.
    MIN_REQUEST_INTERVAL = 1.5  # 초
    # 그래도 일시 차단이 걸리면(롤링 윈도우 추정) 냉각 후 재시도해야 풀린다
    RATE_LIMIT_COOLDOWN = 20.0  # 초
    _rate_lock = threading.Lock()
    _last_fetch_at = 0.0
    _cooldown_until = 0.0

    # 2026-07-31: SSG가 python-requests의 TLS 지문(JA3)을 첫 요청부터 403으로
    # 차단하기 시작 (shinsegaemall 포함 전 서브도메인 실측). curl_cffi의
    # chrome 위장으로는 동일 페이지가 200으로 열림을 실측 확인 → HTTP 수집을
    # curl_cffi(impersonate="chrome")로 전환. 세션은 쿠키(ak_bmsc 등) 누적을
    # 위해 클래스 전역으로 재사용하고, curl_cffi 세션의 스레드 안전성이
    # 보장되지 않아 실제 요청은 락으로 직렬화한다 (요청 간격 1.5초 강제로
    # 어차피 병렬 이득이 없음).
    _http_session = None
    _http_lock = threading.Lock()
    HTTP_TIMEOUT = 30  # 초

    def __init__(self):
        super().__init__(use_selenium=False)

    @classmethod
    def _get_http_session(cls):
        if cls._http_session is None:
            # curl_cffi는 scrapling[fetchers]의 의존성 — 사용 시점에만 import
            from curl_cffi import requests as curl_requests

            cls._http_session = curl_requests.Session(impersonate="chrome")
        return cls._http_session

    def _http_get(self, url: str) -> Optional[str]:
        try:
            with SSGCrawler._http_lock:
                response = self._get_http_session().get(
                    url,
                    timeout=self.HTTP_TIMEOUT,
                    headers={"Accept-Language": "ko-KR,ko;q=0.9"},
                )
            if response.status_code != 200:
                logger.warning(f"[SSG] HTTP {response.status_code}: {url[:60]}")
                return None
            return response.text
        except Exception as e:
            logger.warning(f"[SSG] 요청 실패: {e}")
            return None

    def _rewrite_blocked_url(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.netloc.lower() in self.BLOCKED_HOSTS:
            return urlunsplit(
                ("https", self.REWRITE_HOST, parts.path, parts.query, parts.fragment)
            )
        return url

    def fetch_page(self, url: str, wait_time: int = 2) -> Optional[str]:
        fetch_url = self._rewrite_blocked_url(url)
        if fetch_url != url:
            logger.info(f"[SSG] 봇 차단 도메인 → 서브도메인 우회: {fetch_url[:70]}...")

        cls = SSGCrawler
        with cls._rate_lock:
            now = time.monotonic()
            wait = max(
                cls.MIN_REQUEST_INTERVAL - (now - cls._last_fetch_at),
                cls._cooldown_until - now,
            )
            if wait > 0:
                time.sleep(wait)
            cls._last_fetch_at = time.monotonic()

        html = self._http_get(fetch_url)
        if html is None:
            # 일시 차단(429 추정) — 다음 요청(재시도 포함)은 냉각 후에 나가도록
            with cls._rate_lock:
                cls._cooldown_until = time.monotonic() + cls.RATE_LIMIT_COOLDOWN
            if fetch_url != url:
                # 레이트리밋은 일시적일 수 있으므로 crawl_price의 재시도(백오프)에 맡긴다
                raise Exception(self.REWRITE_FAIL_ERROR)
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

    # 배송비 안내 텍스트가 들어있는 컨테이너 (www 새 DOM의 area-detail 포함)
    DELIVERY_TEXT_CONTAINERS = [".area-detail", "[class*='delivery']", ".cdtl_dl"]

    def _extract_delivery(self, soup, price=None):
        fee = None
        for selector in self.DELIVERY_SELECTORS:
            elem = soup.select_one(selector)
            if elem:
                digits = re.sub(r"[^\d]", "", elem.get_text())
                fee = int(digits) if digits else 0
                break
        if fee is None:
            fee = self._delivery_fee_from_text(soup)
        if fee is None:
            return 0, "무료"
        # "M원 이상 구매 시 무료배송" 조건: 상품 가격이 기준 이상이면 무료
        if fee > 0 and price:
            threshold = self._free_delivery_threshold(soup)
            if threshold and price >= threshold:
                return 0, "무료"
        return fee, ("유료" if fee > 0 else "무료")

    def _delivery_text_blocks(self, soup):
        seen, blocks = set(), []
        for selector in self.DELIVERY_TEXT_CONTAINERS:
            try:
                for elem in soup.select(selector):
                    if id(elem) not in seen:
                        seen.add(id(elem))
                        blocks.append(elem.get_text(" ", strip=True))
            except Exception:
                continue
        return blocks

    def _delivery_fee_from_text(self, soup):
        """선택자가 못 잡는 DOM(예: www 새 디자인의 '배송비 : 3,000원' 텍스트)
        에서 배송비를 추출. 반품/교환/추가 배송비는 제외한다."""
        for text in self._delivery_text_blocks(soup):
            for m in re.finditer(r"([가-힣]*)\s*배송비\s*:?\s*([\d,]+)\s*원", text):
                prefix = m.group(1)
                if any(kw in prefix for kw in ("반품", "교환", "추가")):
                    continue
                return int(m.group(2).replace(",", ""))
        return None

    def _free_delivery_threshold(self, soup):
        """'M원 이상 구매 시 무료배송' 안내의 기준 금액."""
        for text in self._delivery_text_blocks(soup):
            m = re.search(r"([\d,]+)\s*원\s*이상[^0-9]{0,20}무료\s*배송", text)
            if m:
                return int(m.group(1).replace(",", ""))
        return None

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

        delivery_price, delivery_status = self._extract_delivery(
            soup, price=(coupon_price or sale_price)
        )
        logger.info(
            f"[SSG] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
