"""CJ 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
import re
import logging
import threading

logger = logging.getLogger(__name__)


class CJCrawler(BaseCrawler):
    """CJ온스타일 크롤러 (scrapling Camoufox) - 판매가/쿠폰적용가 분리"""

    SALE_PRICE_SELECTORS = [
        ".item_price strong.ff_price",
        ".opt_area .item_price strong.ff_price",
        ".price_bx .txt_price .ff_price",
        ".txt_price .ff_price",
        ".total_price_wrap strong.ff_price",
        ".price_area .price_txt > strong.ff_price",
        ".ff_price",
    ]
    # 실사이트에서 쿠폰가 노출 사례로 미검증 (2026-07 검증 시 쿠폰 미노출)
    # — 쿠폰가 오탐 시 이 선택자부터 의심할 것.
    COUPON_PRICE_SELECTORS = [
        ".coupon_price .ff_price",
        ".price_coupon .ff_price",
        ".benefit_price .ff_price",
    ]
    DELIVERY_SELECTORS = [
        ".gift_delivery_wrap .delivery_fees strong",
        ".delivery_fees strong",
    ]
    SOLD_OUT_SELECTORS = [
        ".btn_soldout",
        ".soldout_layer .txt",
    ]
    # 판매종료/삭제 상품 URL은 CJ가 메인 페이지로 클라이언트 리다이렉트한다.
    # #main_cont는 메인에만 있고 상품 페이지에는 없다 (2026-07 실측) —
    # 대기 조건에 포함해 리다이렉트를 15초 타임아웃 대신 ~2초에 감지한다.
    MAIN_REDIRECT_SELECTOR = "#main_cont"
    # 배송비 영역은 가격보다 0.01~0.35초 늦게 렌더된다 (2026-07-31 실측).
    # 가격 출현 즉시 HTML을 캡처하면 그 틈에 배송비가 간헐적으로 누락되어
    # 같은 상품의 배송비/최종가격이 실행마다 달라짐 → 가격이 뜬 뒤 배송비
    # 영역을 짧게 추가 대기한다. cap은 영역이 아예 없는 DOM 변형 대비.
    DELIVERY_WAIT_SELECTOR = ".gift_delivery_wrap, .delivery_fees"
    DELIVERY_WAIT_TIMEOUT_MS = 3_000

    # CJ 상품 페이지는 SPA라 정적 HTML에 가격이 없고(2026-07 실측), headless
    # Chrome(Selenium)은 서버에서 봇 감지로 빈 페이지를 받는다. Camoufox
    # (위장 Firefox, scrapling StealthySession)는 headless로도 감지를 통과해
    # 가격이 렌더된 HTML을 받음을 실측 확인 → 브라우저 방식을 이것으로 교체.
    # Camoufox 브라우저 1개를 클래스 전역으로 공유하고 fetch를 락으로 직렬화.
    # 15초/내부재시도 1회: 없는 상품 URL은 CJ 메인으로 리다이렉트되어 대기
    # 선택자가 영원히 안 나타난다. 기본값(30초×3회)이면 건당 ~90초 + 세션
    # 파괴 예외까지 발생(2026-07 실측) → 15초 후 정상 반환되도록 제한.
    FETCH_TIMEOUT_MS = 15_000
    FETCH_RETRIES = 1
    _stealthy_session = None
    _stealthy_lock = threading.Lock()
    # StealthySession은 Playwright 기반이라 브라우저를 시작한 스레드에서만
    # 조작할 수 있다. 엔진 워커 스레드들이 번갈아 호출하면 스레드가 바뀔
    # 때마다 예외 → 브라우저 재생성 반복 → 못 닫은 좀비 브라우저 누적으로
    # 메모리 고갈(2026-07 서버 실측: 7개). 세션 생성·fetch·close 전부를
    # 아래 1-스레드 실행기에서만 수행해 브라우저를 한 스레드에 고정한다.
    _fetch_executor = None
    # 브라우저 자체 제한(15초×재시도 1회)보다 넉넉한 안전망 — 초과 시 행 방지
    FETCH_RESULT_TIMEOUT_S = 90

    def __init__(self):
        super().__init__(use_selenium=False)

    def get_price_wait_selectors(self, url: str) -> List[str]:
        return [
            ".item_price strong.ff_price",
            ".ff_price",
            ".txt_price .ff_price",
            ".total_price_wrap strong.ff_price",
            # 변형 DOM: 가격이 .price_area 아래에만 있는 페이지 (2026-07 실측)
            ".price_area .price_txt > strong.ff_price",
        ]

    def get_sold_out_selectors(self) -> List[str]:
        return self.SOLD_OUT_SELECTORS

    @classmethod
    def _create_stealthy_session(cls):
        # scrapling은 무거운 선택 의존성이라 실제 사용 시점에만 import
        from scrapling.fetchers import StealthySession

        session = StealthySession(
            headless=True, timeout=cls.FETCH_TIMEOUT_MS, retries=cls.FETCH_RETRIES
        )
        session.start()
        return session

    def _price_wait_union(self) -> str:
        # bare '.ff_price'는 SPA 셸에 빈 스켈레톤으로 존재해 렌더 전에 매칭
        # → 간헐적으로 가격 없는 HTML이 반환(not_found 오탐)되므로 대기
        # 조건에서 제외한다 (추출 fallback으로는 계속 사용).
        return ", ".join(
            s for s in self.get_price_wait_selectors("") if s != ".ff_price"
        )

    def _wait_selector(self) -> str:
        # 가격 또는 품절 표시 중 먼저 나타나는 쪽까지 대기 (union CSS).
        # 품절 페이지에는 가격 요소가 없어 가격만 기다리면 타임아웃까지 지연됨.
        return ", ".join(
            [self._price_wait_union()]
            + self.SOLD_OUT_SELECTORS
            + [self.MAIN_REDIRECT_SELECTOR]
        )

    def _page_action(self, page):
        # scrapling fetch의 wait_selector 대신 여기서 대기한다 — 둘을 같이
        # 쓰면 선택자가 영원히 안 나타나는 페이지에서 대기가 2번(2배) 걸림.
        try:
            page.locator(self._wait_selector()).first.wait_for(
                state="attached", timeout=self.FETCH_TIMEOUT_MS
            )
        except Exception:
            return page  # 타임아웃 — 현재 DOM 그대로 캡처
        try:
            if page.locator(self._price_wait_union()).count() > 0:
                # 품절/메인 리다이렉트가 아닌 상품 페이지 — 배송비 영역 추가 대기
                page.locator(self.DELIVERY_WAIT_SELECTOR).first.wait_for(
                    state="attached", timeout=self.DELIVERY_WAIT_TIMEOUT_MS
                )
        except Exception:
            pass
        return page

    @classmethod
    def _get_fetch_executor(cls) -> ThreadPoolExecutor:
        with cls._stealthy_lock:
            if cls._fetch_executor is None:
                cls._fetch_executor = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="cj-browser"
                )
            return cls._fetch_executor

    def fetch_page(self, url: str, wait_time: int = 2) -> Optional[str]:
        future = self._get_fetch_executor().submit(self._fetch_in_browser_thread, url)
        try:
            return future.result(timeout=self.FETCH_RESULT_TIMEOUT_S)
        except Exception as e:
            logger.warning(f"[CJ] 브라우저 스레드 응답 없음/실패: {e}")
            return None

    def _fetch_in_browser_thread(self, url: str) -> Optional[str]:
        # 전용 스레드(_fetch_executor) 안에서만 실행된다 — 직접 호출 금지.
        cls = CJCrawler
        try:
            if cls._stealthy_session is None:
                logger.info("[CJ] 스텔스 브라우저 세션 생성 중...")
                cls._stealthy_session = cls._create_stealthy_session()
            page = cls._stealthy_session.fetch(url, page_action=self._page_action)
        except Exception as e:
            logger.warning(f"[CJ] 요청 실패, 브라우저 세션 재생성 예정: {e}")
            if cls._stealthy_session is not None:
                try:
                    cls._stealthy_session.close()
                except Exception:
                    pass
                cls._stealthy_session = None
            return None
        if page.status != 200:
            logger.warning(f"[CJ] HTTP {page.status}: {url[:60]}")
            return None
        return page.html_content

    # 주의: _close_driver를 오버라이드해 공유 세션을 닫으면 안 된다 —
    # 엔진이 스레드별 크롤러 인스턴스를 쓰므로 한 인스턴스의 정리(__del__ 포함)가
    # 다른 스레드가 쓰는 브라우저를 죽인다. Camoufox 세션은 프로세스 수명 동안
    # 유지한다 (요청 실패 시 fetch_page 안에서만 재생성).

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
        logger.info(f"[CJ] URL: {url[:60]}... HTML 길이: {len(html)}")

        sale_price = self.select_first_price(soup, self.SALE_PRICE_SELECTORS)
        coupon_price = self.select_first_price(soup, self.COUPON_PRICE_SELECTORS)

        if sale_price is None and coupon_price is None:
            if self.detect_sold_out(soup):
                logger.info("[CJ] 품절 표시 감지")
                return self.build_price_result(
                    url, delivery_price=None, delivery_status="매진/품절",
                    status="sold_out", error="페이지에서 품절 표시 감지",
                )
            if soup.select_one(self.MAIN_REDIRECT_SELECTOR):
                logger.info("[CJ] 메인 리다이렉트 감지 — 판매종료/삭제 상품 추정")
                return self.build_price_result(
                    url, status="not_found",
                    error="CJ 메인으로 리다이렉트됨 (판매종료/삭제 상품 추정)",
                )
            logger.warning("[CJ] ❌ 가격을 찾지 못함")
            return self.build_price_result(url)

        delivery_price, delivery_status = self._extract_delivery(soup)
        logger.info(
            f"[CJ] ✅ 판매가: {sale_price}, 쿠폰적용가: {coupon_price}, 배송비: {delivery_price}"
        )
        return self.build_price_result(
            url, sale_price=sale_price, coupon_price=coupon_price,
            delivery_price=delivery_price, delivery_status=delivery_status,
        )
