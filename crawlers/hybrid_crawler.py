"""
하이브리드 크롤러 - HTTP 요청과 브라우저 기반 크롤링을 조합

특징:
- HTTP 요청 우선 시도 (빠르고 리소스 효율적)
- JavaScript 렌더링 필요 시에만 브라우저 사용
- 브라우저 풀을 통한 리소스 관리
- 자동 재시도 및 에러 핸들링
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from bs4 import BeautifulSoup
import requests
import time
import json
import os
import logging
from pathlib import Path

from utils.retry_handler import (
    retry,
    CrawlingError,
    NetworkError,
    BotDetectedError,
    ParseError,
)

logger = logging.getLogger(__name__)


class SiteConfig:
    """사이트 설정 로더"""

    _config: Dict = None
    _config_path = Path(__file__).parent.parent / "config" / "sites_config.json"

    @classmethod
    def load(cls) -> Dict:
        """설정 로드 (캐싱)"""
        if cls._config is None:
            try:
                with open(cls._config_path, "r", encoding="utf-8") as f:
                    cls._config = json.load(f)
            except FileNotFoundError:
                logger.warning("sites_config.json not found, using defaults")
                cls._config = {"sites": {}, "defaults": {}}
        return cls._config

    @classmethod
    def get_site_config(cls, domain: str) -> Dict:
        """도메인에 대한 설정 반환"""
        config = cls.load()

        # 정확히 일치하는 설정 찾기
        for site_domain, site_config in config.get("sites", {}).items():
            if site_domain in domain:
                return site_config

        # 기본 설정 반환
        return config.get(
            "defaults",
            {
                "requires_javascript": True,
                "wait_time": 3,
                "retry_count": 3,
                "timeout": 30,
            },
        )

    @classmethod
    def get_performance_config(cls) -> Dict:
        """성능 설정 반환"""
        config = cls.load()
        return config.get(
            "performance",
            {
                "max_concurrent_http_requests": 10,
                "max_concurrent_browser_requests": 2,
                "batch_size": 10,
            },
        )


class HybridCrawler(ABC):
    """
    하이브리드 크롤러 베이스 클래스

    HTTP 요청을 우선 시도하고, 실패하거나 JS 렌더링이 필요한 경우에만 브라우저 사용
    """

    def __init__(self):
        self.session = requests.Session()
        self._setup_session()

        # 사이트별 설정
        self.site_domain: str = ""
        self._site_config: Optional[Dict] = None

    def _setup_session(self):
        """HTTP 세션 설정"""
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

    @property
    def site_config(self) -> Dict:
        """사이트 설정"""
        if self._site_config is None:
            self._site_config = SiteConfig.get_site_config(self.site_domain)
        return self._site_config

    @property
    def requires_javascript(self) -> bool:
        """JavaScript 렌더링 필요 여부"""
        return self.site_config.get("requires_javascript", True)

    @property
    def wait_time(self) -> int:
        """대기 시간"""
        return self.site_config.get("wait_time", 3)

    @property
    def retry_count(self) -> int:
        """재시도 횟수"""
        return self.site_config.get("retry_count", 3)

    @property
    def timeout(self) -> int:
        """타임아웃"""
        return self.site_config.get("timeout", 30)

    def _fetch_with_http(self, url: str) -> Optional[str]:
        """HTTP 요청으로 페이지 가져오기 (빠름)"""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            # 인코딩 처리
            response.encoding = response.apparent_encoding or "utf-8"
            html = response.text

            # 봇 감지 체크 (HTML이 너무 짧으면 차단 가능성)
            if len(html) < 2000:
                logger.warning(
                    f"[HTTP] HTML이 너무 짧음 ({len(html)}bytes), 봇 차단 가능성"
                )
                return None

            logger.debug(f"[HTTP] 성공: {url[:50]}... ({len(html)}bytes)")
            return html

        except requests.Timeout:
            logger.warning(f"[HTTP] 타임아웃: {url[:50]}...")
            raise NetworkError(f"타임아웃: {url}")
        except requests.RequestException as e:
            logger.warning(f"[HTTP] 요청 실패: {e}")
            raise NetworkError(f"요청 실패: {e}")

    def _fetch_with_browser(self, url: str) -> Optional[str]:
        """브라우저로 페이지 가져오기 (JavaScript 렌더링)"""
        from utils.browser_pool import get_browser_pool

        pool = get_browser_pool()

        try:
            with pool.get_browser() as driver:
                logger.debug(f"[Browser] 로딩: {url[:50]}...")
                driver.get(url)

                # 기본 대기
                time.sleep(self.wait_time)

                # JavaScript 완료 대기
                for _ in range(5):
                    ready_state = driver.execute_script("return document.readyState")
                    if ready_state == "complete":
                        break
                    time.sleep(1)

                html = driver.page_source

                # 봇 감지 체크
                if len(html) < 2000:
                    logger.warning(
                        f"[Browser] HTML이 너무 짧음 ({len(html)}bytes), 봇 차단 가능성"
                    )

                    # 추가 대기 후 재시도
                    time.sleep(3)
                    driver.refresh()
                    time.sleep(self.wait_time)
                    html = driver.page_source

                    if len(html) < 2000:
                        raise BotDetectedError("봇이 감지되어 차단됨")

                logger.debug(f"[Browser] 성공: {url[:50]}... ({len(html)}bytes)")
                return html

        except Exception as e:
            logger.error(f"[Browser] 실패: {e}")
            raise

    def fetch_page(self, url: str) -> Optional[str]:
        """
        페이지 가져오기 (하이브리드)

        1. JavaScript 렌더링이 필요 없으면 HTTP 요청 시도
        2. HTTP 실패하거나 JS 필요하면 브라우저 사용
        """
        html = None

        # JavaScript 렌더링이 필요 없는 사이트는 HTTP 우선
        if not self.requires_javascript:
            try:
                html = self._fetch_with_http(url)
                if html and self._validate_html(html, url):
                    return html
            except Exception as e:
                logger.debug(f"[Hybrid] HTTP 시도 실패, 브라우저로 전환: {e}")

        # 브라우저로 시도
        try:
            html = self._fetch_with_browser(url)
            return html
        except Exception as e:
            logger.error(f"[Hybrid] 브라우저도 실패: {e}")
            raise

    def _validate_html(self, html: str, url: str) -> bool:
        """
        HTML 유효성 검증 (서브클래스에서 오버라이드 가능)

        HTTP로 가져온 HTML에 필요한 데이터가 있는지 확인
        없으면 브라우저로 재시도
        """
        # 기본: HTML 길이 확인
        if len(html) < 2000:
            return False

        # 특정 사이트의 가격 요소 존재 확인
        soup = BeautifulSoup(html, "lxml")

        # 사이트 설정에서 선택자 확인
        price_selectors = self.site_config.get("selectors", {}).get("price", [])
        for selector in price_selectors:
            if soup.select_one(selector):
                return True

        # 선택자가 없거나 찾지 못하면 추가 검증 필요
        return len(html) > 5000

    @retry(max_attempts=3, delay=2, backoff=1.5)
    def crawl_price(self, url: str) -> Dict:
        """
        가격 크롤링 (재시도 포함)
        """
        try:
            html = self.fetch_page(url)

            if not html:
                raise CrawlingError("페이지를 가져올 수 없습니다")

            result = self.extract_price(html, url)

            # 가격 추출 검증
            if result.get("상품 가격") is None:
                logger.warning(f"가격 추출 실패: {url[:50]}...")
                # 가격이 없으면 에러로 간주하여 재시도
                # raise ParseError("가격을 찾을 수 없습니다")

            return result

        except Exception as e:
            logger.error(f"크롤링 실패: {url[:50]}... - {e}")
            return {
                "상품 url": url,
                "상품 가격": None,
                "배송비": None,
                "배송비 여부": "크롤링 실패",
                "최종 가격": None,
                "에러 발생": str(e),
                "추출 날짜": self._get_timestamp(),
            }

    @abstractmethod
    def extract_price(self, html: str, url: str) -> Dict:
        """가격 정보 추출 (서브클래스에서 구현)"""
        pass

    def _get_timestamp(self) -> str:
        """타임스탬프 생성"""
        from datetime import datetime

        return datetime.now().isoformat()

    def close(self):
        """리소스 정리"""
        if self.session:
            self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
