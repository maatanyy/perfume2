"""브라우저 풀 매니저 - 메모리 효율적인 브라우저 인스턴스 관리"""

import threading
import time
import queue
import psutil
import os
import signal
from typing import Optional, Dict, Any
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


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


def is_browser_session_dead(error_msg: str) -> bool:
    """브라우저 세션이 죽었는지 확인"""
    error_lower = error_msg.lower()
    return any(kw in error_lower for kw in SESSION_DEAD_KEYWORDS)


@dataclass
class BrowserStats:
    """브라우저 통계"""

    total_created: int = 0
    total_requests: int = 0
    current_active: int = 0
    recycled_count: int = 0
    last_cleanup: Optional[datetime] = None


class BrowserInstance:
    """개별 브라우저 인스턴스 래퍼"""

    def __init__(self, driver, instance_id: int):
        self.driver = driver
        self.instance_id = instance_id
        self.request_count = 0
        self.created_at = datetime.now()
        self.last_used_at = datetime.now()
        self.pids: list = []
        self._lock = threading.Lock()
        self._is_dead = False  # 세션 죽음 플래그

    def use(self):
        """사용 기록"""
        with self._lock:
            self.request_count += 1
            self.last_used_at = datetime.now()

    def mark_dead(self):
        """세션 죽음 마킹"""
        self._is_dead = True

    @property
    def is_dead(self) -> bool:
        """세션이 죽었는지 확인"""
        return self._is_dead

    def is_session_alive(self) -> bool:
        """세션이 살아있는지 확인 (간단한 health check)"""
        if self._is_dead:
            return False
        try:
            # 간단한 JavaScript 실행으로 세션 상태 확인
            self.driver.execute_script("return 1;")
            return True
        except Exception as e:
            error_msg = str(e)
            if is_browser_session_dead(error_msg):
                self._is_dead = True
                logger.warning(
                    f"브라우저 #{self.instance_id} 세션 죽음 감지: {error_msg[:50]}..."
                )
            return False

    @property
    def age_seconds(self) -> float:
        """인스턴스 생성 후 경과 시간 (초)"""
        return (datetime.now() - self.created_at).total_seconds()

    @property
    def idle_seconds(self) -> float:
        """마지막 사용 후 유휴 시간 (초)"""
        return (datetime.now() - self.last_used_at).total_seconds()


class BrowserPool:
    """
    브라우저 풀 매니저

    특징:
    - 최대 브라우저 수 제한 (기본 2개)
    - 요청 수 기반 자동 재활용 (메모리 누수 방지)
    - Context Manager 지원으로 안전한 리소스 정리
    - 유휴 브라우저 자동 정리
    """

    # 기본 설정 (4GB RAM, 2 vCPU 최적화)
    DEFAULT_MAX_BROWSERS = 2
    DEFAULT_MAX_REQUESTS_PER_BROWSER = 30  # 30회 요청 후 재활용
    DEFAULT_MAX_AGE_SECONDS = 300  # 5분 후 재활용
    DEFAULT_IDLE_TIMEOUT = 60  # 60초 유휴 시 정리

    def __init__(
        self,
        max_browsers: int = None,
        max_requests_per_browser: int = None,
        max_age_seconds: int = None,
        idle_timeout: int = None,
    ):
        self.max_browsers = max_browsers or self.DEFAULT_MAX_BROWSERS
        self.max_requests_per_browser = (
            max_requests_per_browser or self.DEFAULT_MAX_REQUESTS_PER_BROWSER
        )
        self.max_age_seconds = max_age_seconds or self.DEFAULT_MAX_AGE_SECONDS
        self.idle_timeout = idle_timeout or self.DEFAULT_IDLE_TIMEOUT

        self._pool: queue.Queue = queue.Queue()
        self._active_browsers: Dict[int, BrowserInstance] = {}
        self._lock = threading.RLock()
        self._instance_counter = 0
        self._stats = BrowserStats()
        self._shutdown = False

        # 백그라운드 정리 스레드
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

        logger.info(
            f"BrowserPool 초기화: max={self.max_browsers}, "
            f"max_requests={self.max_requests_per_browser}"
        )

    def _create_browser(self) -> Optional[BrowserInstance]:
        """새 브라우저 인스턴스 생성"""
        try:
            # undetected-chromedriver 우선 사용
            try:
                import undetected_chromedriver as uc

                options = uc.ChromeOptions()
                options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1920,1080")
                options.add_argument("--lang=ko-KR")

                # 메모리 최적화 옵션
                options.add_argument("--disable-extensions")
                options.add_argument("--disable-plugins")
                options.add_argument("--disable-images")  # 이미지 로드 비활성화
                options.add_argument("--blink-settings=imagesEnabled=false")
                options.add_argument("--disable-javascript-harmony-shipping")
                options.add_argument("--disable-background-networking")
                options.add_argument("--disable-default-apps")
                options.add_argument("--disable-sync")
                options.add_argument("--disable-translate")
                options.add_argument("--hide-scrollbars")
                options.add_argument("--metrics-recording-only")
                options.add_argument("--mute-audio")
                options.add_argument("--no-first-run")
                options.add_argument("--safebrowsing-disable-auto-update")

                # 메모리 제한
                options.add_argument("--js-flags=--max-old-space-size=256")

                driver = uc.Chrome(
                    options=options, version_main=None, use_subprocess=False
                )
                logger.info("[BrowserPool] undetected-chromedriver로 브라우저 생성")

            except ImportError:
                # 일반 selenium 사용
                from selenium import webdriver
                from selenium.webdriver.chrome.options import Options

                options = Options()
                options.add_argument("--headless=new")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-dev-shm-usage")
                options.add_argument("--disable-gpu")
                options.add_argument("--window-size=1920,1080")
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_argument("--disable-extensions")
                options.add_argument("--disable-plugins")
                options.add_argument("--blink-settings=imagesEnabled=false")
                options.add_argument("--js-flags=--max-old-space-size=256")

                options.add_experimental_option(
                    "excludeSwitches", ["enable-automation"]
                )
                options.add_experimental_option("useAutomationExtension", False)

                driver = webdriver.Chrome(options=options)
                logger.info("[BrowserPool] selenium으로 브라우저 생성")

            # 인스턴스 생성
            with self._lock:
                self._instance_counter += 1
                instance_id = self._instance_counter
                self._stats.total_created += 1

            instance = BrowserInstance(driver, instance_id)

            # PID 추적
            try:
                if (
                    hasattr(driver, "service")
                    and driver.service
                    and hasattr(driver.service, "process")
                ):
                    pid = driver.service.process.pid
                    instance.pids.append(pid)
                    parent = psutil.Process(pid)
                    for child in parent.children(recursive=True):
                        instance.pids.append(child.pid)
            except Exception as e:
                logger.debug(f"PID 추적 실패: {e}")

            logger.info(f"[BrowserPool] 브라우저 #{instance_id} 생성 완료")
            return instance

        except Exception as e:
            logger.error(f"[BrowserPool] 브라우저 생성 실패: {e}")
            return None

    def _destroy_browser(self, instance: BrowserInstance):
        """브라우저 인스턴스 완전 종료"""
        if not instance:
            return

        try:
            logger.info(f"[BrowserPool] 브라우저 #{instance.instance_id} 종료 중...")

            # 1. Selenium quit
            try:
                instance.driver.quit()
            except Exception:
                pass

            # 2. Service 프로세스 종료
            try:
                if hasattr(instance.driver, "service") and instance.driver.service:
                    if instance.driver.service.process:
                        instance.driver.service.process.terminate()
                        time.sleep(0.3)
                        instance.driver.service.process.kill()
            except Exception:
                pass

            # 3. 추적된 모든 PID 강제 종료
            for pid in instance.pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass

            logger.info(f"[BrowserPool] 브라우저 #{instance.instance_id} 종료 완료")

        except Exception as e:
            logger.error(f"[BrowserPool] 브라우저 종료 오류: {e}")

    def _should_recycle(self, instance: BrowserInstance) -> bool:
        """브라우저 재활용 필요 여부 판단"""
        # 세션이 죽었으면 무조건 재활용
        if instance.is_dead:
            logger.warning(f"브라우저 #{instance.instance_id}: 세션 죽음 - 재활용 필요")
            return True

        # 세션 상태 확인 (health check)
        if not instance.is_session_alive():
            logger.warning(
                f"브라우저 #{instance.instance_id}: 세션 응답 없음 - 재활용 필요"
            )
            return True

        # 요청 수 초과
        if instance.request_count >= self.max_requests_per_browser:
            logger.debug(
                f"브라우저 #{instance.instance_id}: 요청 수 초과 ({instance.request_count})"
            )
            return True

        # 최대 수명 초과
        if instance.age_seconds >= self.max_age_seconds:
            logger.debug(
                f"브라우저 #{instance.instance_id}: 수명 초과 ({instance.age_seconds:.0f}초)"
            )
            return True

        return False

    @contextmanager
    def get_browser(self, timeout: float = 30.0):
        """
        브라우저 인스턴스 획득 (Context Manager)

        사용법:
            with pool.get_browser() as driver:
                driver.get(url)
                html = driver.page_source
        """
        instance = None
        acquired_from_pool = False

        try:
            with self._lock:
                # 풀에서 가져오기 시도
                while not self._pool.empty():
                    try:
                        instance = self._pool.get_nowait()

                        # 재활용 필요 여부 확인
                        if self._should_recycle(instance):
                            self._stats.recycled_count += 1
                            self._destroy_browser(instance)
                            instance = None
                            continue

                        acquired_from_pool = True
                        break
                    except queue.Empty:
                        break

                # 풀이 비었고, 생성 가능하면 새로 생성
                if instance is None:
                    current_count = len(self._active_browsers) + self._pool.qsize()
                    if current_count < self.max_browsers:
                        instance = self._create_browser()

                # 그래도 없으면 대기
                if instance is None and not self._pool.empty():
                    instance = self._pool.get(timeout=timeout)
                    acquired_from_pool = True

                    if self._should_recycle(instance):
                        self._stats.recycled_count += 1
                        self._destroy_browser(instance)
                        instance = self._create_browser()

                if instance:
                    self._active_browsers[instance.instance_id] = instance
                    self._stats.current_active = len(self._active_browsers)

            if instance is None:
                raise RuntimeError("브라우저를 획득할 수 없습니다. 풀이 가득 찼습니다.")

            instance.use()
            self._stats.total_requests += 1

            yield instance.driver

        except Exception as e:
            error_msg = str(e)
            logger.error(f"[BrowserPool] 브라우저 획득/사용 오류: {error_msg}")

            # 세션 죽음 감지 시 인스턴스 마킹 및 정리
            if instance:
                if is_browser_session_dead(error_msg):
                    instance.mark_dead()
                    logger.warning(
                        f"[BrowserPool] 브라우저 #{instance.instance_id} 세션 죽음으로 폐기"
                    )
                self._destroy_browser(instance)
                with self._lock:
                    self._active_browsers.pop(instance.instance_id, None)
            raise

        finally:
            # 사용 완료 후 풀에 반환
            if instance:
                with self._lock:
                    self._active_browsers.pop(instance.instance_id, None)
                    self._stats.current_active = len(self._active_browsers)

                    # 재활용이 필요하면 종료, 아니면 풀에 반환
                    if self._should_recycle(instance):
                        self._stats.recycled_count += 1
                        self._destroy_browser(instance)
                    else:
                        self._pool.put(instance)

    def _cleanup_loop(self):
        """백그라운드 정리 루프"""
        while not self._shutdown:
            try:
                time.sleep(30)  # 30초마다 확인
                self._cleanup_idle_browsers()
            except Exception as e:
                logger.error(f"[BrowserPool] 정리 루프 오류: {e}")

    def _cleanup_idle_browsers(self):
        """유휴 브라우저 정리"""
        with self._lock:
            # 풀에서 유휴 상태가 오래된 브라우저 정리
            cleaned = 0
            temp_list = []

            while not self._pool.empty():
                try:
                    instance = self._pool.get_nowait()
                    if instance.idle_seconds > self.idle_timeout:
                        self._destroy_browser(instance)
                        cleaned += 1
                    else:
                        temp_list.append(instance)
                except queue.Empty:
                    break

            # 정리되지 않은 인스턴스 다시 풀에 넣기
            for instance in temp_list:
                self._pool.put(instance)

            if cleaned > 0:
                logger.info(f"[BrowserPool] 유휴 브라우저 {cleaned}개 정리됨")
                self._stats.last_cleanup = datetime.now()

    def shutdown(self):
        """풀 종료 - 모든 브라우저 정리"""
        logger.info("[BrowserPool] 종료 중...")
        self._shutdown = True

        with self._lock:
            # 활성 브라우저 정리
            for instance_id, instance in list(self._active_browsers.items()):
                self._destroy_browser(instance)
            self._active_browsers.clear()

            # 풀의 브라우저 정리
            while not self._pool.empty():
                try:
                    instance = self._pool.get_nowait()
                    self._destroy_browser(instance)
                except queue.Empty:
                    break

        logger.info("[BrowserPool] 종료 완료")

    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환"""
        with self._lock:
            return {
                "total_created": self._stats.total_created,
                "total_requests": self._stats.total_requests,
                "current_active": self._stats.current_active,
                "pool_size": self._pool.qsize(),
                "recycled_count": self._stats.recycled_count,
                "max_browsers": self.max_browsers,
                "last_cleanup": (
                    self._stats.last_cleanup.isoformat()
                    if self._stats.last_cleanup
                    else None
                ),
            }

    def __del__(self):
        """소멸자"""
        try:
            self.shutdown()
        except Exception:
            pass


# 전역 브라우저 풀 인스턴스
_browser_pool: Optional[BrowserPool] = None
_pool_lock = threading.Lock()


def get_browser_pool(
    max_browsers: int = None, max_requests_per_browser: int = None
) -> BrowserPool:
    """전역 브라우저 풀 가져오기 (싱글톤)"""
    global _browser_pool

    with _pool_lock:
        if _browser_pool is None:
            _browser_pool = BrowserPool(
                max_browsers=max_browsers,
                max_requests_per_browser=max_requests_per_browser,
            )
        return _browser_pool


def shutdown_browser_pool():
    """전역 브라우저 풀 종료"""
    global _browser_pool

    with _pool_lock:
        if _browser_pool:
            _browser_pool.shutdown()
            _browser_pool = None
