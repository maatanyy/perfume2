"""신세계 쇼핑 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, List, Optional
import re
import logging
import threading
import time

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

    # 2026-08-01 실측: 단건 요청은 343KB 정상 페이지가 오지만, 잡 실행 중
    # 요청이 몰리면 가격이 없는 ~81KB 축소 페이지가 섞여 와 21%가 추출실패로
    # 기록됐다 (같은 URL을 서버에서 단건 수집하면 성공). 요청 간격을 두고,
    # 축소 페이지를 받으면 1회 재요청한다. 판매종료 상품도 축소 페이지를
    # 주므로, 재요청 후에도 같으면 그대로 두어 '추출실패'로 남긴다.
    # 간격은 적응형이다: 평소에는 짧게(0.3초) 가고, 축소 페이지가 나오면
    # 그때만 넓혔다가 정상 응답이 쌓이면 원래대로 돌아온다. 고정 1초는
    # 안전하지만 잡 시간을 13분 → 30분으로 늘렸다 (2026-08-01 실측).
    MIN_REQUEST_INTERVAL = 0.3  # 초 (기본/하한)
    MAX_REQUEST_INTERVAL = 2.0  # 초 (상한)
    WIDEN_FACTOR = 2.0  # 축소 페이지 감지 시 간격 배수
    DECAY_FACTOR = 0.7  # 회복 시 간격 축소 배수
    DECAY_AFTER_GOOD = 20  # 정상 응답 N회마다 한 단계 회복
    DEGRADED_HTML_MAX = 150_000  # 정상 페이지는 ~340KB
    DEGRADED_RETRY_DELAY = 3.0  # 초
    PRICE_MARKER = "_bestPrice"
    _rate_lock = threading.Lock()
    _last_fetch_at = 0.0
    _current_interval = MIN_REQUEST_INTERVAL
    _good_streak = 0

    def __init__(self):
        super().__init__(use_selenium=False)

    def _looks_degraded(self, html: Optional[str]) -> bool:
        return bool(
            html
            and len(html) < self.DEGRADED_HTML_MAX
            and self.PRICE_MARKER not in html
        )

    @classmethod
    def _note_degraded(cls):
        """축소 페이지 감지 — 간격을 넓힌다 (상한까지)."""
        cls._good_streak = 0
        cls._current_interval = min(
            cls.MAX_REQUEST_INTERVAL, cls._current_interval * cls.WIDEN_FACTOR
        )

    @classmethod
    def _note_good(cls):
        """정상 응답 — 일정 횟수마다 간격을 원래대로 좁힌다 (하한까지)."""
        cls._good_streak += 1
        if cls._good_streak >= cls.DECAY_AFTER_GOOD:
            cls._good_streak = 0
            cls._current_interval = max(
                cls.MIN_REQUEST_INTERVAL, cls._current_interval * cls.DECAY_FACTOR
            )

    def _gated_fetch(self, url: str, wait_time: int) -> Optional[str]:
        cls = ShinsegaeCrawler
        with cls._rate_lock:
            wait = cls._current_interval - (time.monotonic() - cls._last_fetch_at)
            if wait > 0:
                time.sleep(wait)
            cls._last_fetch_at = time.monotonic()
        return super().fetch_page(url, wait_time)

    def fetch_page(self, url: str, wait_time: int = 2) -> Optional[str]:
        cls = ShinsegaeCrawler
        html = self._gated_fetch(url, wait_time)
        if not self._looks_degraded(html):
            cls._note_good()
            return html
        cls._note_degraded()
        logger.warning(
            f"[신세계] 축소 페이지 감지({len(html)}B) — 간격 {cls._current_interval:.1f}초로 조정, "
            f"{self.DEGRADED_RETRY_DELAY}초 후 재요청"
        )
        time.sleep(self.DEGRADED_RETRY_DELAY)
        retry_html = self._gated_fetch(url, wait_time)
        if retry_html and not self._looks_degraded(retry_html):
            cls._note_good()
            return retry_html
        return retry_html or html

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
