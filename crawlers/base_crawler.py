"""크롤러 베이스 클래스"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from bs4 import BeautifulSoup
import requests
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


class BaseCrawler(ABC):
    """크롤러 베이스 클래스"""

    def __init__(self, use_selenium: bool = False):
        self.use_selenium = use_selenium
        self.driver = None
        self._chrome_pids = []  # Chrome 프로세스 PID 추적
        self._driver_lock = threading.Lock()  # 스레드 안전성
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        self._driver_lock = threading.Lock()  # 스레드 안전성

    def _get_driver(self):
        """Selenium 드라이버 생성 (스레드 안전)"""
        with self._driver_lock:  # 락으로 보호
            if self.driver is None:
                print(f"[DEBUG] Creating Chrome driver for {self.__class__.__name__}")
                chrome_options = Options()
                chrome_options.add_argument("--headless")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--window-size=1920,1080")
                chrome_options.add_argument(
                    "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )

                try:
                    self.driver = webdriver.Chrome(options=chrome_options)

                    # Chrome 관련 PID 수집 (driver, chromedriver, chrome 프로세스)
                    try:
                        if self.driver.service.process:
                            driver_pid = self.driver.service.process.pid
                            self._chrome_pids.append(driver_pid)
                            # 자식 프로세스도 추적
                            parent = psutil.Process(driver_pid)
                            for child in parent.children(recursive=True):
                                self._chrome_pids.append(child.pid)
                            print(f"[DEBUG] Chrome PIDs tracked: {self._chrome_pids}")
                    except Exception as e:
                        print(f"[DEBUG] PID tracking failed: {e}")

                except Exception as e:
                    print(f"Chrome 드라이버 생성 실패: {e}")
                    self.use_selenium = False

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
                time.sleep(wait_time)
                html = driver.page_source
                print(f"[DEBUG] Page loaded, HTML length: {len(html)}")
                return html
            except Exception as e:
                print(f"[ERROR] Selenium으로 페이지 로드 실패: {e}")
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
        self, url: str, max_retries: int = 2, auto_close: bool = False
    ) -> Dict:
        """가격 크롤링 (재시도 로직 포함)"""
        try:
            for attempt in range(1, max_retries + 1):
                try:
                    wait_time = self.get_wait_time(url)
                    html = self.fetch_page(url, wait_time)

                    if not html:
                        raise Exception("페이지를 가져올 수 없습니다.")

                    result = self.extract_price(html, url)

                    # 가격이 정상적으로 추출되었는지 확인
                    if result.get("상품 가격") is not None:
                        return result

                    # 가격이 없으면 재시도
                    if attempt < max_retries:
                        time.sleep(1 * attempt)

                except Exception as e:
                    if attempt == max_retries:
                        return {
                            "상품 url": url,
                            "상품 가격": None,
                            "배송비": None,
                            "배송비 여부": "크롤링 실패",
                            "최종 가격": None,
                            "에러 발생": str(e),
                            "추출 날짜": time.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    time.sleep(1 * attempt)

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
        if "ssg.com" in url_lower:
            return 4  # SSG 대기 시간 최적화 (6초 → 4초)
        return 2  # 기본 대기 시간 최적화

    def __del__(self):
        """소멸자 - 드라이버 정리 (중요!)"""
        try:
            self._close_driver()
        except:
            pass
