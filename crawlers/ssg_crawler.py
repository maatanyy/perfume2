"""SSG 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit
import os
import platform
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

    # shinsegaemall도 짧은 시간에 요청이 몰리면 일시 차단(429)된다.
    # 2026-08-01 실측: 1.5초 간격은 11건 후 429, 3초 간격은 20건 중 1건만
    # 429(냉각으로 회복). 클래스 전역 최소 요청 간격을 강제한다.
    MIN_REQUEST_INTERVAL = 3.0  # 초
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

    # IP 차단 서킷 브레이커 (2026-07-31 실측): Akamai 차단은 요청이 올 때마다
    # 점수가 갱신되는 방식이라, 차단된 상태로 잡 전체(수백 요청)를 계속
    # 돌리면 차단이 영원히 안 풀리는 악순환이 된다. 연속 403이 임계치에
    # 달하면 일정 시간 요청 자체를 생략하고 명확한 오류로 빠르게 기록한다.
    # 잡 길이가 ~45분이라 차단이 길면 잡 포기와 같다 (2026-08-01 실측:
    # 30분 차단으로 882건 중 656건이 통째로 스킵됨). 짧게 끊고 재시도한다.
    BLOCK_FAST_FAIL_DURATION = 300.0  # 초 (5분)
    BLOCK_FAST_FAIL_ERROR = (
        "SSG 차단 감지 — 브라우저 쿠키 워밍업 반복 실패, 남은 SSG 요청 생략"
    )
    _fast_fail_until = 0.0
    # 403 연속 이 횟수 전에는 쿠키를 버리지 않고 냉각 후 재시도한다
    MAX_403_BEFORE_REWARM = 3
    _consecutive_403 = 0

    # 브라우저 쿠키 워밍업 (2026-08-01 실측): SSG 상품 페이지가 Akamai 센서
    # 쿠키(_abck 등)를 요구하도록 바뀌어 순수 HTTP는 첫 요청부터 403이다.
    # 실제 브라우저로 메인을 방문(마우스/스크롤 포함)해 센서 검증을 통과한
    # 쿠키를 확보하면, 같은 쿠키+UA로 보내는 HTTP 요청이 200으로 열린다.
    # headless로 얻은 쿠키는 거부되므로 headful로 띄운다 — 서버(디스플레이
    # 없음)에서는 Xvfb 가상 디스플레이가 필요하다.
    WARMUP_MAIN_URL = "https://shinsegaemall.ssg.com/"
    WARMUP_ITEM_URL = (
        "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1000860342112"
    )
    WARMUP_TIMEOUT_MS = 40_000
    WARMUP_RESULT_TIMEOUT_S = 120
    # 워밍업 자체가 무거우므로(브라우저 기동 ~25초) 최소 간격을 둔다
    WARMUP_MIN_INTERVAL = 60.0  # 초
    MAX_WARMUP_FAILURES = 3
    _needs_warm = True
    _warm_failures = 0
    _last_warm_at = 0.0
    _warm_ua = None
    _warm_lock = threading.Lock()
    # Playwright는 브라우저를 시작한 스레드에서만 조작 가능 — CJ와 같은
    # 이유로 워밍업 전체를 전용 스레드 1개에 고정한다
    _warm_executor = None
    _virtual_display = None

    def __init__(self):
        super().__init__(use_selenium=False)

    # 데이터센터 IP는 봇 차단 서비스가 위험군으로 분류할 수 있다. 환경변수
    # SSG_PROXY(예: http://user:pw@host:port)가 설정되면 브라우저 워밍업과
    # HTTP 수집 모두 해당 프록시를 경유한다. 미설정이면 직접 요청(기존 동작).
    PROXY_ENV = "SSG_PROXY"

    @classmethod
    def _proxy(cls) -> Optional[str]:
        return os.environ.get(cls.PROXY_ENV) or None

    @classmethod
    def _session_kwargs(cls) -> Dict:
        proxy = cls._proxy()
        if not proxy:
            return {}
        return {"proxies": {"http": proxy, "https": proxy}}

    @classmethod
    def _warmup_session_kwargs(cls) -> Dict:
        kwargs = {"headless": False, "timeout": cls.WARMUP_TIMEOUT_MS, "retries": 1}
        proxy = cls._proxy()
        if proxy:
            kwargs["proxy"] = proxy
        return kwargs

    @classmethod
    def _get_http_session(cls):
        if cls._http_session is None:
            # curl_cffi는 scrapling[fetchers]의 의존성 — 사용 시점에만 import
            from curl_cffi import requests as curl_requests

            cls._http_session = curl_requests.Session(
                impersonate=cls._warm_impersonate(), **cls._session_kwargs()
            )
        return cls._http_session

    # --- 워밍업 브라우저 선택 ---
    # 2026-08-01 실측: 서버는 GPU가 없어 WebGL이 소프트웨어 렌더러(llvmpipe)로
    # 노출되고, 이 지문 탓에 한국 주거용 프록시 IP로 나가도 상품 페이지가 403.
    # (같은 코드가 실제 PC에서는 통과 — 브라우저 출구 IP를 프록시로 확인함)
    # Camoufox는 지문을 브라우저 내부에서 위장해 JS로 탐지되지 않는다.
    # Camoufox는 Firefox 기반이라 이후 HTTP 재생도 Firefox로 위장해야 한다.
    WARMUP_OS = "windows"
    WARMUP_LOCALE = "ko-KR"
    # Camoufox 내장 WebGL 지문 DB에 존재하는 조합이어야 한다 (없는 값이면
    # 실행 자체가 거부됨). 윈도우 사용자 중 가장 흔한 조합을 쓴다.
    WARMUP_WEBGL = (
        "Google Inc. (NVIDIA)",
        "ANGLE (NVIDIA, NVIDIA GeForce GTX 980 Direct3D11 vs_5_0 ps_5_0), or similar",
    )

    @classmethod
    def _available_memory_mb(cls) -> int:
        try:
            import psutil

            return int(psutil.virtual_memory().available / 1024 / 1024)
        except Exception:
            return -1

    @classmethod
    def _camoufox_available(cls) -> bool:
        try:
            import camoufox.sync_api  # noqa: F401
        except Exception:
            return False
        return True

    @classmethod
    def _warm_impersonate(cls) -> str:
        return "firefox" if cls._camoufox_available() else "chrome"

    @classmethod
    def _camoufox_options(cls) -> Dict:
        options = {
            "headless": True,
            "os": cls.WARMUP_OS,
            "locale": cls.WARMUP_LOCALE,
            # humanize(자동 커서 시뮬레이션)는 headless에서 무한 대기하는
            # 사례가 있어 끈다 (2026-08-01 실측: 5분 넘게 진행 없음).
            # 사람 흔적은 _browse_for_cookies의 명시적 마우스/스크롤로 공급.
            "humanize": False,
            "webgl_config": cls.WARMUP_WEBGL,
        }
        proxy = cls._proxy()
        if proxy:
            from scrapling.engines.toolbelt.navigation import construct_proxy_dict

            options["proxy"] = construct_proxy_dict(proxy)
        return options

    # --- 브라우저 쿠키 워밍업 ---

    @classmethod
    def _ensure_virtual_display(cls):
        """서버(디스플레이 없는 Linux)에서 headful 브라우저를 띄우기 위한
        Xvfb 가상 디스플레이. 맥/윈도우나 DISPLAY가 이미 있으면 불필요."""
        if cls._virtual_display is not None:
            return
        if platform.system() != "Linux" or os.environ.get("DISPLAY"):
            return
        from pyvirtualdisplay import Display

        cls._virtual_display = Display(visible=False, size=(1920, 1080))
        cls._virtual_display.start()
        logger.info("[SSG] Xvfb 가상 디스플레이 시작")

    @classmethod
    def _get_warm_executor(cls) -> ThreadPoolExecutor:
        if cls._warm_executor is None:
            cls._warm_executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="ssg-warm"
            )
        return cls._warm_executor

    @classmethod
    def _run_warmup(cls) -> Optional[Dict]:
        """브라우저를 띄워 센서 쿠키를 확보한다. {"cookies": [...], "ua": str}
        또는 실패 시 None. 전용 스레드에서 실행된다."""
        future = cls._get_warm_executor().submit(cls._warmup_in_browser_thread)
        try:
            return future.result(timeout=cls.WARMUP_RESULT_TIMEOUT_S)
        except Exception as e:
            logger.warning(f"[SSG] 워밍업 스레드 실패: {e}")
            return None

    @classmethod
    def _browse_for_cookies(cls, page, harvested: Dict):
        """메인 방문 → 사람 흔적 공급 → 상품 페이지. 센서 쿠키를 수확한다.
        (Playwright/Camoufox 어느 쪽 page 객체든 동일 API로 동작)"""
        page.goto(cls.WARMUP_MAIN_URL)
        page.wait_for_timeout(3000)
        # 센서에 사람 흔적(마우스/스크롤) 공급 — 없으면 검증이 통과되지 않음
        for x, y in ((200, 300), (400, 350), (600, 500)):
            page.mouse.move(x, y)
            page.wait_for_timeout(300)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(2500)
        page.goto(cls.WARMUP_ITEM_URL)
        try:
            page.locator("em.ssg_price").first.wait_for(state="attached", timeout=12_000)
            harvested["ok"] = True
        except Exception:
            harvested["ok"] = False
        try:
            harvested["html_len"] = len(page.content())
        except Exception:
            harvested["html_len"] = 0
        harvested["cookies"] = page.context.cookies()
        harvested["ua"] = page.evaluate("navigator.userAgent")
        return page

    @classmethod
    def _warmup_in_browser_thread(cls) -> Optional[Dict]:
        # 전용 스레드(_warm_executor) 안에서만 실행된다 — 직접 호출 금지.
        if cls._camoufox_available():
            return cls._warmup_with_camoufox()
        return cls._warmup_with_patchright()

    @classmethod
    def _warmup_with_camoufox(cls) -> Optional[Dict]:
        from camoufox.sync_api import Camoufox

        harvested: Dict = {}
        try:
            with Camoufox(**cls._camoufox_options()) as browser:
                page = browser.new_page()
                try:
                    cls._browse_for_cookies(page, harvested)
                finally:
                    page.close()
        except Exception as e:
            logger.warning(f"[SSG] Camoufox 워밍업 실패: {e}")
            return None
        if not harvested.get("ok") or not harvested.get("cookies"):
            # 실패 원인(차단 vs 자원 부족)을 로그만으로 구분할 수 있게 남긴다
            logger.warning(
                f"[SSG] Camoufox가 상품 페이지를 열지 못함 "
                f"(HTML {harvested.get('html_len', 0):,}B, "
                f"쿠키 {len(harvested.get('cookies') or [])}개, "
                f"여유 메모리 {cls._available_memory_mb()}MB)"
            )
            return None
        return {
            "cookies": harvested["cookies"],
            "ua": harvested["ua"],
            "impersonate": "firefox",
        }

    @classmethod
    def _warmup_with_patchright(cls) -> Optional[Dict]:
        from scrapling.fetchers import StealthySession

        cls._ensure_virtual_display()
        harvested: Dict = {}
        session = None
        try:
            session = StealthySession(**cls._warmup_session_kwargs())
            session.start()
            session.fetch(
                cls.WARMUP_ITEM_URL,
                page_action=lambda page: cls._browse_for_cookies(page, harvested),
            )
        except Exception as e:
            logger.warning(f"[SSG] 브라우저 워밍업 실패: {e}")
            return None
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
        if not harvested.get("ok") or not harvested.get("cookies"):
            logger.warning("[SSG] 워밍업 브라우저가 상품 페이지를 열지 못함")
            return None
        return {
            "cookies": harvested["cookies"],
            "ua": harvested["ua"],
            "impersonate": "chrome",
        }

    @classmethod
    def _apply_warm_cookies(cls, data: Dict):
        from curl_cffi import requests as curl_requests

        # 쿠키를 발급한 브라우저와 같은 계열로 위장해야 유효하다
        # (Camoufox=Firefox, patchright=Chrome)
        session = curl_requests.Session(
            impersonate=data.get("impersonate", "chrome"), **cls._session_kwargs()
        )
        for cookie in data["cookies"]:
            try:
                session.cookies.set(
                    cookie["name"], cookie["value"], domain=cookie.get("domain", "")
                )
            except Exception:
                continue
        cls._http_session = session
        cls._warm_ua = data.get("ua")

    @classmethod
    def seconds_until_ready(cls) -> int:
        """차단 해제까지 남은 초. 잡 말미 재시도 패스가 이만큼 기다렸다가
        재시도하면 차단 구간에 스킵된 항목을 회복할 수 있다."""
        remaining = cls._fast_fail_until - time.monotonic()
        return int(remaining) if remaining > 0 else 0

    @classmethod
    def _is_blocked(cls) -> bool:
        """차단 중인지. 만료됐으면 실패 카운터를 리셋해 다시 기회를 준다
        (리셋하지 않으면 이후 실패 1회마다 재차단이 반복된다)."""
        if time.monotonic() < cls._fast_fail_until:
            return True
        if cls._warm_failures >= cls.MAX_WARMUP_FAILURES:
            cls._warm_failures = 0
            logger.info("[SSG] 차단 해제 — 워밍업 재시도")
        return False

    @classmethod
    def _ensure_warm(cls) -> bool:
        """쿠키가 필요하면 워밍업한다. 사용 가능하면 True."""
        with cls._warm_lock:
            # 차단 중에는 워밍업도 하지 않는다 (만료 시 카운터 리셋도 여기서)
            if cls._is_blocked():
                return False
            if not cls._needs_warm:
                return True
            elapsed = time.monotonic() - cls._last_warm_at
            if cls._last_warm_at and elapsed < cls.WARMUP_MIN_INTERVAL:
                time.sleep(cls.WARMUP_MIN_INTERVAL - elapsed)
            cls._last_warm_at = time.monotonic()
            logger.info("[SSG] 브라우저 쿠키 워밍업 시작...")
            data = cls._run_warmup()
            if not data:
                cls._warm_failures += 1
                if cls._warm_failures >= cls.MAX_WARMUP_FAILURES:
                    cls._fast_fail_until = (
                        time.monotonic() + cls.BLOCK_FAST_FAIL_DURATION
                    )
                    logger.error(
                        f"[SSG] 워밍업 {cls._warm_failures}회 연속 실패 — "
                        f"{int(cls.BLOCK_FAST_FAIL_DURATION / 60)}분간 SSG 요청 생략"
                    )
                return False
            cls._apply_warm_cookies(data)
            cls._warm_failures = 0
            cls._needs_warm = False
            logger.info("[SSG] 쿠키 워밍업 완료")
            return True

    def _http_get(self, url: str) -> Optional[str]:
        cls = SSGCrawler
        if not cls._ensure_warm():
            return None
        headers = {"Accept-Language": "ko-KR,ko;q=0.9", "Referer": cls.WARMUP_MAIN_URL}
        if cls._warm_ua:
            # 센서 쿠키는 발급받은 브라우저의 UA와 함께 와야 유효하다
            headers["User-Agent"] = cls._warm_ua
        try:
            with cls._http_lock:
                response = self._get_http_session().get(
                    url, timeout=self.HTTP_TIMEOUT, headers=headers
                )
            if response.status_code == 403:
                # 403이 곧 쿠키 만료는 아니다 — 요청이 몰리면 일시적으로도
                # 403이 온다. 그때 쿠키를 버리고 브라우저를 다시 띄우면,
                # 이미 차단 중이라 워밍업까지 403을 받아 실패가 연쇄된다
                # (2026-08-01 실측: 152건 스킵). 연속 N회 전에는 냉각 후
                # 같은 쿠키로 재시도한다.
                cls._consecutive_403 += 1
                cls._cooldown_until = time.monotonic() + cls.RATE_LIMIT_COOLDOWN
                if cls._consecutive_403 >= cls.MAX_403_BEFORE_REWARM:
                    cls._needs_warm = True
                    logger.warning(
                        f"[SSG] 403 연속 {cls._consecutive_403}회 — 쿠키 만료 판정, 재워밍업"
                    )
                else:
                    logger.warning(
                        f"[SSG] HTTP 403 ({cls._consecutive_403}/{cls.MAX_403_BEFORE_REWARM}) "
                        f"— 냉각 후 같은 쿠키로 재시도: {url[:50]}"
                    )
                return None
            if response.status_code != 200:
                # 429 등은 레이트리밋 — 쿠키는 유효하므로 냉각으로 회복
                logger.warning(f"[SSG] HTTP {response.status_code}: {url[:60]}")
                return None
            cls._consecutive_403 = 0
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
        cls = SSGCrawler
        # 서킷 브레이커: 차단 판정 중에는 요청(과 요청 간격 대기) 없이 즉시 실패
        if cls._is_blocked():
            raise Exception(self.BLOCK_FAST_FAIL_ERROR)

        fetch_url = self._rewrite_blocked_url(url)
        if fetch_url != url:
            logger.info(f"[SSG] 봇 차단 도메인 → 서브도메인 우회: {fetch_url[:70]}...")
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
