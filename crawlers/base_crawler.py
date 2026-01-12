"""크롤러 베이스 클래스"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from bs4 import BeautifulSoup
import requests

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
        self._chrome_pids = []  # Chrome 프로세스 PID 추적
        self._driver_lock = threading.Lock()  # 스레드 안전성
        self.session = requests.Session()
        # 더 현실적인 User-Agent 및 헤더 (봇 감지 우회)
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
        self._driver_lock = threading.Lock()  # 스레드 안전성

    def _get_driver(self):
        """Selenium 드라이버 생성 (스레드 안전) - undetected-chromedriver 우선 사용"""
        global UNDETECTED_AVAILABLE  # 전역 변수 사용 선언

        with self._driver_lock:  # 락으로 보호
            if self.driver is None:
                print(f"[DEBUG] Creating Chrome driver for {self.__class__.__name__}")

                # undetected-chromedriver 사용 (봇 감지 우회)
                if UNDETECTED_AVAILABLE:
                    try:
                        print("[DEBUG] Using undetected-chromedriver (봇 감지 우회)")
                        options = uc.ChromeOptions()
                        options.add_argument("--headless=new")  # headless 모드
                        options.add_argument("--no-sandbox")
                        options.add_argument("--disable-dev-shm-usage")
                        options.add_argument("--disable-gpu")
                        options.add_argument("--window-size=1920,1080")
                        options.add_argument("--lang=ko-KR")
                        options.add_argument(
                            "--accept-lang=ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
                        )

                        # undetected-chromedriver로 드라이버 생성 (자동으로 봇 감지 우회)
                        self.driver = uc.Chrome(
                            options=options, version_main=None, use_subprocess=False
                        )
                        print("[DEBUG] Undetected Chrome driver created successfully")
                    except Exception as e:
                        print(
                            f"[WARNING] undetected-chromedriver 실패, 일반 selenium 사용: {e}"
                        )
                        UNDETECTED_AVAILABLE = False  # 실패 시 일반 드라이버 사용

                # undetected-chromedriver를 사용할 수 없으면 일반 selenium 사용
                if not UNDETECTED_AVAILABLE or self.driver is None:
                    print("[DEBUG] Using standard selenium Chrome driver")
                    from selenium.webdriver.chrome.options import Options

                    chrome_options = Options()
                    chrome_options.add_argument("--headless=new")
                    chrome_options.add_argument("--no-sandbox")
                    chrome_options.add_argument("--disable-dev-shm-usage")
                    chrome_options.add_argument("--disable-gpu")
                    chrome_options.add_argument("--window-size=1920,1080")

                    # 봇 감지 우회 옵션
                    chrome_options.add_argument(
                        "--disable-blink-features=AutomationControlled"
                    )
                    chrome_options.add_argument("--disable-infobars")
                    chrome_options.add_argument("--disable-extensions")
                    chrome_options.add_argument("--no-first-run")
                    chrome_options.add_argument("--no-default-browser-check")
                    chrome_options.add_argument("--disable-default-apps")
                    chrome_options.add_argument("--lang=ko-KR")
                    chrome_options.add_argument(
                        "--accept-lang=ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
                    )

                    # User-Agent
                    chrome_options.add_argument(
                        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )

                    # 자동화 감지 방지
                    chrome_options.add_experimental_option(
                        "excludeSwitches", ["enable-automation", "enable-logging"]
                    )
                    chrome_options.add_experimental_option(
                        "useAutomationExtension", False
                    )

                    try:
                        from selenium import webdriver

                        self.driver = webdriver.Chrome(options=chrome_options)

                        # 자동화 감지 방지 JavaScript 실행
                        self.driver.execute_cdp_cmd(
                            "Page.addScriptToEvaluateOnNewDocument",
                            {
                                "source": """
                                Object.defineProperty(navigator, 'webdriver', {
                                    get: () => undefined
                                });
                                window.chrome = { runtime: {} };
                                Object.defineProperty(navigator, 'plugins', {
                                    get: () => [1, 2, 3, 4, 5]
                                });
                                Object.defineProperty(navigator, 'languages', {
                                    get: () => ['ko-KR', 'ko', 'en-US', 'en']
                                });
                            """
                            },
                        )
                    except Exception as e:
                        print(f"Chrome 드라이버 생성 실패: {e}")
                        self.use_selenium = False
                        return None

                # Chrome 관련 PID 수집 (driver, chromedriver, chrome 프로세스)
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
                        # 자식 프로세스도 추적
                        parent = psutil.Process(driver_pid)
                        for child in parent.children(recursive=True):
                            self._chrome_pids.append(child.pid)
                        print(f"[DEBUG] Chrome PIDs tracked: {self._chrome_pids}")
                except Exception as e:
                    print(f"[DEBUG] PID tracking failed: {e}")

            return self.driver

    def _close_driver(self):
        """Selenium 드라이버 종료 - 모든 Chrome 프로세스 강제 종료"""
        with self._driver_lock:
            if self.driver:
                try:
                    print(
                        f"[DEBUG] Closing Chrome driver for {self.__class__.__name__}"
                    )

                    # 1. Selenium quit 시도
                    try:
                        self.driver.quit()
                    except:
                        pass

                    # 2. Service 프로세스 강제 종료
                    try:
                        if self.driver.service.process:
                            self.driver.service.process.terminate()
                            time.sleep(0.5)
                            self.driver.service.process.kill()
                    except:
                        pass

                    # 3. 수집한 모든 PID 강제 종료
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

    def fetch_page(self, url: str, wait_time: int = 2) -> Optional[str]:
        """페이지 가져오기"""
        if self.use_selenium:
            try:
                driver = self._get_driver()
                if driver is None:
                    print(
                        f"[ERROR] Chrome driver is None for {self.__class__.__name__}"
                    )
                    return None

                print(f"[DEBUG] Loading URL: {url[:50]}...")
                driver.get(url)

                # SSG Shopping은 더 긴 대기 시간 필요
                url_lower = url.lower()
                is_ssg_shopping = (
                    "shinsegaetvshopping.com" in url_lower or "ssg_shoping" in url_lower
                )

                if is_ssg_shopping:
                    wait_time = max(wait_time, 10)  # 최소 10초 대기
                    # 추가로 페이지 스크롤 (동적 콘텐츠 로딩 유도)
                    try:
                        driver.execute_script(
                            "window.scrollTo(0, document.body.scrollHeight/3);"
                        )
                        time.sleep(2)
                        driver.execute_script("window.scrollTo(0, 0);")
                        time.sleep(1)
                    except:
                        pass

                time.sleep(wait_time)

                # JavaScript 완료 대기 - 여러 번 확인
                try:
                    for attempt in range(5):  # 최대 5번 시도
                        ready_state = driver.execute_script(
                            "return document.readyState"
                        )
                        if ready_state == "complete":
                            # SSG Shopping의 경우 추가로 가격 요소가 로드될 때까지 대기
                            if is_ssg_shopping:
                                try:
                                    # 가격 요소가 로드될 때까지 최대 10초 대기
                                    from selenium.webdriver.support.ui import (
                                        WebDriverWait,
                                    )
                                    from selenium.webdriver.common.by import By
                                    from selenium.webdriver.support import (
                                        expected_conditions as EC,
                                    )

                                    # 여러 선택자 시도
                                    selectors = [
                                        ".price--3",
                                        "._salePrice",
                                        "._bestPrice",
                                        ".div-best ._bestPrice",
                                        ".cdtl_new_price.notranslate .ssg_price",
                                        ".price_total .ssg_price",
                                    ]

                                    found = False
                                    for selector in selectors:
                                        try:
                                            elements = WebDriverWait(driver, 3).until(
                                                EC.presence_of_all_elements_located(
                                                    (By.CSS_SELECTOR, selector)
                                                )
                                            )
                                            if elements:
                                                found = True
                                                break
                                        except:
                                            continue

                                    if not found:
                                        # 요소를 찾지 못했더라도 추가 대기
                                        time.sleep(3)
                                except Exception as e:
                                    print(f"[DEBUG] SSG Shopping 요소 대기 실패: {e}")
                                    time.sleep(3)  # 실패해도 추가 대기
                            break
                        time.sleep(1)
                except Exception as e:
                    print(f"[DEBUG] Ready state 체크 실패: {e}")
                    time.sleep(2)  # 실패 시에도 대기

                html = driver.page_source
                print(f"[DEBUG] Page loaded, HTML length: {len(html)}")

                # HTML이 너무 짧으면 봇 감지 가능성 - 재시도
                if len(html) < 5000:
                    print(
                        f"[WARNING] HTML too short ({len(html)} bytes), possible bot detection - 재시도 중..."
                    )
                    # 추가 대기 후 재시도
                    time.sleep(5)
                    driver.refresh()  # 페이지 새로고침
                    time.sleep(wait_time)
                    html = driver.page_source
                    print(f"[DEBUG] After retry, HTML length: {len(html)}")

                    if len(html) < 5000:
                        print(
                            f"[WARNING] 재시도 후에도 HTML이 짧음 ({len(html)} bytes), 봇 차단 가능성"
                        )

                return html
            except Exception as e:
                error_msg = str(e)
                print(f"[ERROR] Selenium으로 페이지 로드 실패: {error_msg}")

                # Alert 처리 (매진, 품절 등)
                if "alert" in error_msg.lower() or "Alert" in error_msg:
                    try:
                        alert = driver.switch_to.alert
                        alert_text = alert.text
                        alert.accept()  # Alert 닫기
                        print(f"[INFO] Alert 감지됨: {alert_text}")

                        # 매진/품절 관련 메시지 확인
                        skip_keywords = [
                            "매진",
                            "품절",
                            "판매종료",
                            "판매 종료",
                            "sold out",
                            "soldout",
                            "재고없음",
                            "재고 없음",
                            "구매불가",
                            "구매 불가",
                        ]
                        if any(kw in alert_text.lower() for kw in skip_keywords):
                            # 특별한 마커를 반환하여 재시도 방지
                            raise SoldOutError(alert_text)
                    except SoldOutError:
                        raise
                    except:
                        pass

                return None

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

    def crawl_price(
        self, url: str, max_retries: int = 3, auto_close: bool = False
    ) -> Dict:
        """가격 크롤링 (재시도 로직 포함)"""
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    wait_time = self.get_wait_time(url)

                    # SSG Shopping의 경우 재시도 시 더 긴 대기
                    url_lower = url.lower()
                    if (
                        "shinsegaetvshopping.com" in url_lower
                        or "ssg_shoping" in url_lower
                    ) and attempt > 1:
                        wait_time = max(wait_time, 12)  # 재시도 시 더 긴 대기

                    html = self.fetch_page(url, wait_time)

                    if not html:
                        raise Exception("페이지를 가져올 수 없습니다.")

                    # HTML이 너무 짧으면 재시도
                    if len(html) < 2000:
                        print(
                            f"[WARNING] Attempt {attempt}: HTML too short ({len(html)} bytes), retrying..."
                        )
                        if attempt < max_retries:
                            time.sleep(3 * attempt)  # 재시도 간격 증가
                            continue

                    result = self.extract_price(html, url)

                    # 가격이 정상적으로 추출되었는지 확인
                    if result.get("상품 가격") is not None:
                        return result

                    # 가격이 없으면 재시도
                    if attempt < max_retries:
                        print(
                            f"[WARNING] Attempt {attempt}: 가격 추출 실패, 재시도 중..."
                        )
                        time.sleep(2 * attempt)

                except SoldOutError as e:
                    # 매진/품절 - 재시도 없이 즉시 반환
                    print(f"[INFO] 매진/품절 상품 - 재시도 없이 건너뜀: {str(e)}")
                    return {
                        "상품 url": url,
                        "상품 가격": None,
                        "배송비": None,
                        "배송비 여부": "매진/품절",
                        "최종 가격": None,
                        "에러 발생": f"매진/품절: {str(e)}",
                        "추출 날짜": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                except SkipRetryError as e:
                    # 재시도 불필요 에러 - 즉시 반환
                    print(f"[INFO] 재시도 불필요 에러: {str(e)}")
                    return {
                        "상품 url": url,
                        "상품 가격": None,
                        "배송비": None,
                        "배송비 여부": "처리 불가",
                        "최종 가격": None,
                        "에러 발생": str(e),
                        "추출 날짜": time.strftime("%Y-%m-%d %H:%M:%S"),
                    }
                except Exception as e:
                    error_msg = str(e)
                    print(f"[ERROR] Attempt {attempt} failed: {error_msg}")

                    # 매진/품절 관련 키워드 체크 (Alert 외 다른 방식으로 감지된 경우)
                    skip_keywords = [
                        "매진",
                        "품절",
                        "판매종료",
                        "판매 종료",
                        "sold out",
                        "재고없음",
                        "재고 없음",
                        "구매불가",
                        "구매 불가",
                        "삭제된 상품",
                        "존재하지 않는",
                    ]
                    if any(kw in error_msg.lower() for kw in skip_keywords):
                        return {
                            "상품 url": url,
                            "상품 가격": None,
                            "배송비": None,
                            "배송비 여부": "매진/품절",
                            "최종 가격": None,
                            "에러 발생": error_msg,
                            "추출 날짜": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }

                    if attempt == max_retries:
                        return {
                            "상품 url": url,
                            "상품 가격": None,
                            "배송비": None,
                            "배송비 여부": "크롤링 실패",
                            "최종 가격": None,
                            "에러 발생": error_msg,
                            "추출 날짜": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    time.sleep(2 * attempt)  # 재시도 간격 증가

            # 모든 재시도 실패
            return {
                "상품 url": url,
                "상품 가격": None,
                "배송비": None,
                "배송비 여부": "모든 재시도 실패",
                "최종 가격": None,
                "추출 날짜": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        finally:
            # auto_close가 True일 때만 Chrome 종료 (호출자가 관리할 수도 있음)
            if auto_close:
                self._close_driver()

    def get_wait_time(self, url: str) -> int:
        """사이트별 대기 시간 결정"""
        url_lower = url.lower()
        if "shinsegaetvshopping.com" in url_lower or "ssg_shoping" in url_lower:
            return 10  # 신세계TV쇼핑 - JavaScript 많음, 더 긴 대기 필요
        elif "ssg.com" in url_lower:
            return 5  # SSG 대기 시간
        elif "shinsegae" in url_lower:
            return 8  # 신세계TV쇼핑 - JavaScript 많음
        elif "cjonstyle" in url_lower:
            return 5
        return 3  # 기본 대기 시간

    def __del__(self):
        """소멸자 - 드라이버 정리 (중요!)"""
        try:
            self._close_driver()
        except:
            pass
