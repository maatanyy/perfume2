"""크롤러 베이스 클래스"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
import requests
from datetime import datetime

try:
    import undetected_chromedriver as uc
    UNDETECTED_AVAILABLE = True
except ImportError:
    UNDETECTED_AVAILABLE = False
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import threading
import os
import signal
import psutil
from selenium.common.exceptions import WebDriverException, TimeoutException


# 브라우저 세션 죽음 감지 키워드
SESSION_DEAD_KEYWORDS = [
    "connection refused",
    "connection aborted",
    "remotedisconnected",
    "remote end closed connection",
    "max retries exceeded",
    "session deleted",
    "session not created",
    "invalid session id",
    "no such session",
    "session timed out",
    "connection reset",
    "broken pipe",
]

# 품절 감지 키워드 (본문 텍스트용)
SOLD_OUT_KEYWORDS = [
    "품절", "일시품절", "매진", "판매종료", "판매 종료",
    "sold out", "soldout", "재고없음", "재고 없음", "구매불가", "구매 불가",
]

# 범용 품절 선택자 (키워드 텍스트 동반 시에만 품절 판정)
GENERIC_SOLD_OUT_SELECTORS = [
    "[class*='soldout']",
    "[class*='sold_out']",
    "[class*='sold-out']",
]


def is_session_dead(error_msg: str) -> bool:
    """브라우저 세션이 죽었는지 확인"""
    error_lower = error_msg.lower()
    return any(kw in error_lower for kw in SESSION_DEAD_KEYWORDS)


class SoldOutError(Exception):
    """매진/품절 상품 예외 - 재시도 불필요"""
    pass


class SkipRetryError(Exception):
    """재시도 불필요 예외 (비즈니스 로직 에러)"""
    pass


class BaseCrawler(ABC):
    """크롤러 베이스 클래스"""

    def __init__(self, use_selenium: bool = False):
        self.use_selenium = use_selenium
        self.driver = None
        self._chrome_pids = []
        self._driver_lock = threading.Lock()
        self._session_dead = False
        self._driver_creation_attempts = 0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Cache-Control": "max-age=0",
            }
        )

    def get_price_wait_selectors(self, url: str) -> List[str]:
        """
        동적 대기에 사용할 가격 CSS 선택자 목록 반환.
        서브클래스에서 오버라이드하여 사이트별 선택자 제공.
        반환값이 비어있으면 readyState 완료 + 최소 대기 사용.
        """
        return []

    @staticmethod
    def parse_price(text) -> Optional[int]:
        """텍스트에서 가격(int) 추출. 100 이하(%, 개수 등 오탐)는 None."""
        import re as _re
        digits = _re.sub(r"[^\d]", "", text or "")
        if not digits:
            return None
        price = int(digits)
        return price if price > 100 else None

    @staticmethod
    def select_first_price(soup, selectors: List[str]) -> Optional[int]:
        """선택자 목록을 순서대로 시도해 첫 유효 가격 반환."""
        for selector in selectors:
            try:
                elems = soup.select(selector)
            except Exception:
                continue
            for elem in elems:
                price = BaseCrawler.parse_price(elem.get_text())
                if price is not None:
                    return price
        return None

    def build_price_result(
        self,
        url: str,
        sale_price: Optional[int] = None,
        coupon_price: Optional[int] = None,
        delivery_price: Optional[int] = 0,
        delivery_status: str = "무료",
        status: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Dict:
        """표준 결과 dict 생성. 대표가(상품 가격) = 쿠폰적용가 우선."""
        if (
            sale_price is not None
            and coupon_price is not None
            and coupon_price >= sale_price
        ):
            coupon_price = None  # 쿠폰가가 판매가보다 싸지 않으면 쿠폰 없음
        representative = coupon_price if coupon_price is not None else sale_price
        if status is None:
            status = "success" if representative is not None else "not_found"
        total = None
        if representative is not None:
            total = representative + (delivery_price or 0)
        result = {
            "상품 url": url,
            "판매가": sale_price,
            "쿠폰적용가": coupon_price,
            "상품 가격": representative,
            "배송비": delivery_price,
            "배송비 여부": delivery_status,
            "최종 가격": total,
            "결과 상태": status,
            "추출 날짜": datetime.now().isoformat(),
        }
        if error:
            result["에러 발생"] = error
        return result

    def get_sold_out_selectors(self) -> List[str]:
        """사이트별 품절 표시 선택자 (서브클래스 오버라이드)."""
        return []

    def detect_sold_out(self, soup) -> bool:
        """본문에서 품절 표시 감지.
        사이트별 선택자는 요소 존재만으로, 범용 선택자는 키워드 텍스트까지 확인."""
        for selector in self.get_sold_out_selectors():
            try:
                if soup.select_one(selector):
                    return True
            except Exception:
                continue
        for selector in GENERIC_SOLD_OUT_SELECTORS:
            try:
                elems = soup.select(selector)
            except Exception:
                continue
            for elem in elems:
                text = elem.get_text(strip=True).lower()
                if any(kw in text for kw in SOLD_OUT_KEYWORDS):
                    return True
        return False

    def _get_driver(self):
        """Selenium 드라이버 생성 (스레드 안전) - undetected-chromedriver 우선 사용"""
        global UNDETECTED_AVAILABLE

        with self._driver_lock:
            if self._session_dead and self.driver is not None:
                print(f"[INFO] 죽은 세션 감지됨, 드라이버 재생성 중...")
                self._force_close_driver_unsafe()
                self._session_dead = False

            if self.driver is None:
                print(f"[DEBUG] Creating Chrome driver for {self.__class__.__name__}")

                if UNDETECTED_AVAILABLE:
                    try:
                        print("[DEBUG] Using undetected-chromedriver (봇 감지 우회)")
                        options = uc.ChromeOptions()
                        options.add_argument("--headless=new")
                        options.add_argument("--no-sandbox")
                        options.add_argument("--disable-dev-shm-usage")
                        options.add_argument("--disable-gpu")
                        options.add_argument("--window-size=1920,1080")
                        options.add_argument("--lang=ko-KR")
                        options.add_argument("--accept-lang=ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7")

                        prefs = {
                            "profile.managed_default_content_settings.images": 2,
                            "profile.managed_default_content_settings.stylesheets": 2,
                            "profile.managed_default_content_settings.fonts": 2,
                        }
                        options.add_experimental_option("prefs", prefs)

                        self.driver = uc.Chrome(
                            options=options, version_main=None, use_subprocess=False
                        )
                        print("[DEBUG] Undetected Chrome driver created successfully")
                    except Exception as e:
                        print(f"[WARNING] undetected-chromedriver 실패, 일반 selenium 사용: {e}")
                        UNDETECTED_AVAILABLE = False

                if not UNDETECTED_AVAILABLE or self.driver is None:
                    print("[DEBUG] Using standard selenium Chrome driver")
                    from selenium.webdriver.chrome.options import Options

                    chrome_options = Options()
                    chrome_options.add_argument("--headless=new")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("--disable-gpu")
                    chrome_options.add_argument("--window-size=1920,1080")
                    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
                    chrome_options.add_argument("--disable-infobars")
                    chrome_options.add_argument("--disable-extensions")
                    chrome_options.add_argument("--no-first-run")
                    chrome_options.add_argument("--no-default-browser-check")
                    chrome_options.add_argument("--disable-default-apps")
                    chrome_options.add_argument("--lang=ko-KR")
                    chrome_options.add_argument("--accept-lang=ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7")
                    chrome_options.add_argument(
                        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                    chrome_options.add_experimental_option(
                        "excludeSwitches", ["enable-automation", "enable-logging"]
                    )
                    chrome_options.add_experimental_option("useAutomationExtension", False)

                    prefs = {
                        "profile.managed_default_content_settings.images": 2,
                        "profile.managed_default_content_settings.stylesheets": 2,
                        "profile.managed_default_content_settings.fonts": 2,
                    }
                    chrome_options.add_experimental_option("prefs", prefs)

                    try:
                        from selenium import webdriver
                        self.driver = webdriver.Chrome(options=chrome_options)
                        self.driver.execute_cdp_cmd(
                            "Page.addScriptToEvaluateOnNewDocument",
                            {
                                "source": """
                                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                                window.chrome = { runtime: {} };
                                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                                Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
                            """
                            },
                        )
                    except Exception as e:
                        print(f"Chrome 드라이버 생성 실패: {e}")
                        self.use_selenium = False
                        return None

                try:
                    if (
                        self.driver
                        and hasattr(self.driver, "service")
                        and self.driver.service
                        and hasattr(self.driver.service, "process")
                        and self.driver.service.process
                    ):
                        driver_pid = self.driver.service.process.pid
                        self._chrome_pids.append(driver_pid)
                        parent = psutil.Process(driver_pid)
                        for child in parent.children(recursive=True):
                            self._chrome_pids.append(child.pid)
                        print(f"[DEBUG] Chrome PIDs tracked: {self._chrome_pids}")
                except Exception as e:
                    print(f"[DEBUG] PID tracking failed: {e}")

            return self.driver

    def _close_driver(self):
        """Selenium 드라이버 종료"""
        with self._driver_lock:
            self._force_close_driver_unsafe()

    def _force_close_driver_unsafe(self):
        """드라이버 강제 종료 (락 없이 - 내부용)"""
        if self.driver:
            try:
                print(f"[DEBUG] Closing Chrome driver for {self.__class__.__name__}")
                try:
                    self.driver.quit()
                except:
                    pass
                try:
                    if (
                        hasattr(self.driver, "service")
                        and self.driver.service
                        and self.driver.service.process
                    ):
                        self.driver.service.process.terminate()
                        time.sleep(0.5)
                        self.driver.service.process.kill()
                except:
                    pass
                for pid in self._chrome_pids:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except:
                        pass
                self._chrome_pids.clear()
                print(f"[DEBUG] Chrome driver closed successfully")
            except Exception as e:
                print(f"[DEBUG] Error closing driver: {e}")
            finally:
                self.driver = None
                self._session_dead = False

    def _mark_session_dead(self, error_msg: str) -> bool:
        """세션 죽음 감지 및 마킹"""
        if is_session_dead(error_msg):
            print(f"[WARNING] 브라우저 세션 죽음 감지: {error_msg[:100]}...")
            self._session_dead = True
            return True
        return False

    def _recreate_driver_if_needed(self) -> bool:
        """필요시 드라이버 재생성, 성공 여부 반환"""
        if self._session_dead or self.driver is None:
            self._close_driver()
            self._driver_creation_attempts += 1
            if self._driver_creation_attempts > 3:
                print(f"[ERROR] 드라이버 생성 시도 횟수 초과 (3회)")
                return False
            driver = self._get_driver()
            if driver is not None:
                self._driver_creation_attempts = 0
                return True
            return False
        return True

    def _wait_for_price_element(self, driver, url: str, max_wait: int = 12) -> bool:
        """
        가격 요소가 나타날 때까지 동적 대기.
        get_price_wait_selectors()로 사이트별 선택자 사용.
        요소 발견 시 True, 타임아웃 시 False 반환.
        """
        selectors = self.get_price_wait_selectors(url)
        if not selectors:
            return False

        for selector in selectors:
            try:
                WebDriverWait(driver, max_wait).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                print(f"[DEBUG] 가격 요소 발견: {selector}")
                return True
            except TimeoutException:
                continue
            except Exception:
                continue

        print(f"[DEBUG] 가격 요소를 {max_wait}초 내에 찾지 못함, HTML 그대로 파싱")
        return False

    def fetch_page(self, url: str, wait_time: int = 2) -> Optional[str]:
        """페이지 가져오기 - 동적 대기 적용 (세션 죽음 감지 및 자동 복구 포함)"""
        if self.use_selenium:
            if self._session_dead:
                print(f"[INFO] 이전 세션 죽음 감지됨, 드라이버 재생성 중...")
                if not self._recreate_driver_if_needed():
                    print(f"[ERROR] 드라이버 재생성 실패")
                    return None

            try:
                driver = self._get_driver()
                if driver is None:
                    print(f"[ERROR] Chrome driver is None for {self.__class__.__name__}")
                    return None

                print(f"[DEBUG] Loading URL: {url[:50]}...")

                try:
                    driver.get(url)
                except Exception as e:
                    error_msg = str(e)
                    if self._mark_session_dead(error_msg):
                        print(f"[INFO] 세션 죽음으로 인한 드라이버 재생성...")
                        if self._recreate_driver_if_needed():
                            driver = self.driver
                            driver.get(url)
                        else:
                            return None
                    else:
                        raise

                url_lower = url.lower()
                is_ssg_shopping = "shinsegaetvshopping.com" in url_lower

                if is_ssg_shopping:
                    # 신세계TV쇼핑: 스크롤로 동적 콘텐츠 로딩 유도
                    try:
                        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
                        time.sleep(1)
                        driver.execute_script("window.scrollTo(0, 0);")
                        time.sleep(0.5)
                    except:
                        pass

                # ★ 핵심 개선: 고정 sleep 대신 가격 요소 동적 감지
                found = self._wait_for_price_element(driver, url, max_wait=12)

                if not found:
                    # 동적 대기 실패 시 readyState 완료까지만 대기
                    try:
                        WebDriverWait(driver, 10).until(
                            lambda d: d.execute_script("return document.readyState") == "complete"
                        )
                    except:
                        pass
                    # 최소한의 추가 대기 (JS 렌더링 완료용)
                    min_wait = 3 if is_ssg_shopping else 1
                    time.sleep(min_wait)

                html = driver.page_source
                print(f"[DEBUG] Page loaded, HTML length: {len(html)}")

                # HTML이 너무 짧으면 봇 감지 가능성 - 재시도
                if len(html) < 5000:
                    print(f"[WARNING] HTML too short ({len(html)} bytes), 재시도 중...")
                    time.sleep(4)
                    driver.refresh()
                    # 재시도에서도 동적 대기 적용
                    self._wait_for_price_element(driver, url, max_wait=10)
                    html = driver.page_source
                    print(f"[DEBUG] After retry, HTML length: {len(html)}")

                    if len(html) < 5000:
                        print(f"[WARNING] 재시도 후에도 HTML이 짧음, 봇 차단 가능성")

                return html

            except Exception as e:
                error_msg = str(e)
                print(f"[ERROR] Selenium으로 페이지 로드 실패: {error_msg}")

                if self._mark_session_dead(error_msg):
                    print(f"[INFO] 세션 죽음 감지됨, 다음 요청 시 드라이버 재생성 예정")
                    return None

                # Alert 처리 (매진, 품절 등)
                if "alert" in error_msg.lower() or "Alert" in error_msg:
                    try:
                        alert = driver.switch_to.alert
                        alert_text = alert.text
                        alert.accept()
                        print(f"[INFO] Alert 감지됨: {alert_text}")
                        skip_keywords = [
                            "매진", "품절", "판매종료", "판매 종료",
                            "sold out", "soldout", "재고없음", "재고 없음",
                            "구매불가", "구매 불가",
                        ]
                        if any(kw in alert_text.lower() for kw in skip_keywords):
                            raise SoldOutError(alert_text)
                    except SoldOutError:
                        raise
                    except:
                        pass

                return None

        # HTTP 방식
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"페이지 로드 실패: {e}")
            return None

    @abstractmethod
    def extract_price(self, html: str, url: str) -> Dict:
        """가격 정보 추출 (서브클래스에서 구현)"""
        pass

    def crawl_price(self, url: str, max_retries: int = 2, auto_close: bool = False) -> Dict:
        """가격 크롤링 (재시도 로직 포함, 세션 죽음 자동 복구)"""
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    if self._session_dead:
                        print(f"[INFO] Attempt {attempt}: 세션 죽음으로 드라이버 재생성...")
                        if not self._recreate_driver_if_needed():
                            raise Exception("드라이버 재생성 실패")

                    wait_time = self.get_wait_time(url)

                    html = self.fetch_page(url, wait_time)

                    if not html:
                        if self._session_dead and attempt < max_retries:
                            print(f"[INFO] 세션 죽음 감지, 다음 시도에서 복구 예정...")
                            time.sleep(2)
                            continue
                        raise Exception("페이지를 가져올 수 없습니다.")

                    if len(html) < 2000:
                        print(f"[WARNING] Attempt {attempt}: HTML too short ({len(html)} bytes), retrying...")
                        if attempt < max_retries:
                            time.sleep(3 * attempt)
                            continue

                    result = self.extract_price(html, url)

                    if result.get("상품 가격") is not None:
                        return result

                    # 가격을 못 찾았어도 결과 반환 (not_found 상태로 처리됨)
                    print(f"[WARNING] 가격 추출 실패 - 재시도 없이 진행")
                    return result

                except SoldOutError as e:
                    print(f"[INFO] 매진/품절 상품 - 재시도 없이 건너뜀: {str(e)}")
                    return self.build_price_result(
                        url, delivery_price=None, delivery_status="매진/품절",
                        status="sold_out", error=f"매진/품절: {str(e)}",
                    )
                except SkipRetryError as e:
                    print(f"[INFO] 재시도 불필요 에러: {str(e)}")
                    return self.build_price_result(
                        url, delivery_price=None, delivery_status="처리 불가",
                        status="error", error=str(e),
                    )
                except Exception as e:
                    error_msg = str(e)
                    print(f"[ERROR] Attempt {attempt} failed: {error_msg}")

                    skip_keywords = [
                        "매진", "품절", "판매종료", "판매 종료", "sold out",
                        "재고없음", "재고 없음", "구매불가", "구매 불가",
                        "삭제된 상품", "존재하지 않는",
                    ]
                    if any(kw in error_msg.lower() for kw in skip_keywords):
                        return self.build_price_result(
                            url, delivery_price=None, delivery_status="매진/품절",
                            status="sold_out", error=error_msg,
                        )

                    if attempt == max_retries:
                        return self.build_price_result(
                            url, delivery_price=None, delivery_status="크롤링 실패",
                            status="error", error=error_msg,
                        )
                    time.sleep(2 * attempt)

            return self.build_price_result(
                url, delivery_price=None, delivery_status="모든 재시도 실패",
                status="error",
            )
        finally:
            if auto_close:
                self._close_driver()

    def get_wait_time(self, url: str) -> int:
        """사이트별 최대 대기 시간 (동적 대기 실패 시 fallback)"""
        url_lower = url.lower()
        if "shinsegaetvshopping.com" in url_lower:
            return 12
        elif "ssg.com" in url_lower:
            return 8
        elif "shinsegae" in url_lower:
            return 10
        elif "cjonstyle" in url_lower:
            return 8
        elif "lotte" in url_lower:
            return 8
        return 5

    def __del__(self):
        """소멸자 - 드라이버 정리"""
        try:
            self._close_driver()
        except:
            pass
