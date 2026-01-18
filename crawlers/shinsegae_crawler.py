"""신세계 쇼핑 크롤러"""

from crawlers.base_crawler import BaseCrawler
from bs4 import BeautifulSoup
from typing import Dict, Optional
import re
import time
import random
import logging

logger = logging.getLogger(__name__)

# selenium-stealth 사용 가능 여부
try:
    from selenium_stealth import stealth

    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    logger.warning("selenium-stealth not installed, using fallback")


class ShinsegaeCrawler(BaseCrawler):
    """신세계 쇼핑 크롤러 - Selenium 사용 (강화된 봇 우회)"""

    def __init__(self):
        # 서버에서 HTTP 요청이 차단되어 Selenium 사용
        super().__init__(use_selenium=True)
        self._stealth_applied = False

    def _apply_stealth(self, driver):
        """Stealth 모드 적용"""
        if self._stealth_applied:
            return

        if STEALTH_AVAILABLE:
            try:
                stealth(
                    driver,
                    languages=["ko-KR", "ko", "en-US", "en"],
                    vendor="Google Inc.",
                    platform="Win32",
                    webgl_vendor="Intel Inc.",
                    renderer="Intel Iris OpenGL Engine",
                    fix_hairline=True,
                )
                logger.info("[신세계] selenium-stealth 적용 완료")
                self._stealth_applied = True
            except Exception as e:
                logger.warning(f"[신세계] stealth 적용 실패: {e}")
        else:
            # stealth 없을 때 수동 우회
            try:
                driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {
                        "source": """
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                        Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
                        window.chrome = {runtime: {}};
                    """
                    },
                )
                self._stealth_applied = True
            except:
                pass

    def fetch_page(self, url: str, wait_time: int = 2) -> Optional[str]:
        """신세계TV쇼핑 전용 페이지 로딩 (강화된 봇 우회)"""
        if not self.use_selenium:
            return super().fetch_page(url, wait_time)

        try:
            driver = self._get_driver()
            if driver is None:
                logger.error("[신세계] Chrome driver is None")
                return None

            # Stealth 모드 적용
            self._apply_stealth(driver)

            # 랜덤 딜레이 추가 (봇 감지 우회)
            random_delay = random.uniform(2.0, 4.0)
            time.sleep(random_delay)

            logger.info(f"[신세계] Loading URL: {url[:60]}...")

            # 먼저 메인 페이지 방문 (쿠키 획득)
            try:
                driver.get("https://www.shinsegaetvshopping.com")
                time.sleep(3)
                # 쿠키 동의 등 처리
                driver.execute_script("window.scrollTo(0, 100);")
                time.sleep(1)
            except Exception as e:
                logger.debug(f"[신세계] 메인 페이지 방문 중 오류: {e}")

            # 실제 상품 페이지 방문
            driver.get(url)

            # 초기 대기
            time.sleep(4)

            # 페이지 스크롤 (자연스러운 사용자 행동 시뮬레이션)
            try:
                # 천천히 스크롤
                driver.execute_script("window.scrollTo(0, 300);")
                time.sleep(0.5)
                driver.execute_script("window.scrollTo(0, 600);")
                time.sleep(0.5)
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(1)
            except:
                pass

            # 마우스 움직임 시뮬레이션
            try:
                from selenium.webdriver.common.action_chains import ActionChains

                actions = ActionChains(driver)
                body = driver.find_element("tag name", "body")
                actions.move_to_element(body).perform()
                time.sleep(0.5)
            except:
                pass

            # JavaScript 완료 대기
            for attempt in range(10):
                try:
                    ready_state = driver.execute_script("return document.readyState")
                    if ready_state == "complete":
                        break
                except:
                    pass
                time.sleep(1)

            # 추가 대기 (JavaScript 동적 로딩)
            time.sleep(3)

            html = driver.page_source
            logger.info(f"[신세계] Page loaded, HTML length: {len(html)}")

            # HTML이 너무 짧으면 봇 감지 - 여러 번 재시도
            if len(html) < 5000:
                logger.warning(
                    f"[신세계] HTML too short ({len(html)} bytes), 봇 차단 의심"
                )

                # 쿠키 삭제 후 재시도
                try:
                    driver.delete_all_cookies()
                    time.sleep(1)
                except:
                    pass

                # 새로고침 재시도
                for retry in range(3):
                    logger.info(f"[신세계] 재시도 {retry + 1}/3...")
                    time.sleep(random.uniform(3.0, 5.0))

                    # 메인 페이지 다시 방문
                    try:
                        driver.get("https://www.shinsegaetvshopping.com")
                        time.sleep(2)
                    except:
                        pass

                    driver.get(url)
                    time.sleep(5)

                    # 스크롤
                    try:
                        driver.execute_script("window.scrollTo(0, 500);")
                        time.sleep(1)
                        driver.execute_script("window.scrollTo(0, 0);")
                    except:
                        pass

                    html = driver.page_source
                    logger.info(f"[신세계] 재시도 후 HTML length: {len(html)}")

                    if len(html) >= 5000:
                        break

                if len(html) < 5000:
                    logger.error(f"[신세계] 봇 차단 - HTML 길이: {len(html)} bytes")
                    # HTML 내용 일부 출력 (차단 페이지 분석용)
                    logger.error(f"[신세계] 차단 페이지 내용: {html[:800]}")

            return html

        except Exception as e:
            logger.error(f"[신세계] 페이지 로드 실패: {e}")
            return None

    def extract_price(self, html: str, url: str) -> Dict:
        """신세계 쇼핑 가격 정보 추출"""
        soup = BeautifulSoup(html, "lxml")

        product_price = None
        delivery_price = 0
        delivery_status = "무료"

        # 디버깅 로그
        logger.info(f"[신세계] extract_price URL: {url[:60]}...")
        logger.info(f"[신세계] HTML 길이: {len(html)}")

        # 가격 선택자 (우선순위대로) - 2026년 1월 업데이트
        price_selectors = [
            "._bestPrice",  # 할인가 (우선)
            ".price--3 ._bestPrice",
            "._salePrice",  # 정가
            ".div-best ._bestPrice",
            ".total_price .price em",
            ".sale_price",
        ]

        price_elem = None
        for selector in price_selectors:
            elems = soup.select(selector)
            if elems:
                logger.info(f"[신세계] 선택자 '{selector}': {len(elems)}개 발견")

            for elem in elems:
                # 텍스트에서 숫자만 추출 (콤마 제거)
                price_text = re.sub(r"[^\d]", "", elem.get_text())
                price = int(price_text) if price_text else None

                if price and price > 100:  # 100원 이상만 (할인율 제외)
                    price_elem = elem
                    product_price = price
                    logger.info(f"[신세계] ✅ 가격 발견: {product_price}원")
                    break

            if price_elem:
                break

        if product_price is None:
            logger.warning(f"[신세계] ❌ 가격을 찾지 못함")

        total_price = (
            (product_price + delivery_price) if product_price is not None else None
        )

        return {
            "상품 url": url,
            "상품 가격": product_price,
            "배송비": delivery_price,
            "배송비 여부": delivery_status,
            "최종 가격": total_price,
            "추출 날짜": self._get_timestamp(),
        }

    def _get_timestamp(self):
        """타임스탬프 생성"""
        from datetime import datetime

        return datetime.now().isoformat()
