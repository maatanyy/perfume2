"""재시도 및 에러 핸들링 유틸리티"""

import functools
import time
import logging
from typing import Callable, Type, Tuple, Optional
import random

logger = logging.getLogger(__name__)


class CrawlingError(Exception):
    """크롤링 관련 기본 예외"""

    pass


class NetworkError(CrawlingError):
    """네트워크 오류"""

    pass


class BotDetectedError(CrawlingError):
    """봇 감지 오류"""

    pass


class TimeoutError(CrawlingError):
    """타임아웃 오류"""

    pass


class ParseError(CrawlingError):
    """파싱 오류"""

    pass


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Callable = None,
    jitter: bool = True,
):
    """
    재시도 데코레이터

    Args:
        max_attempts: 최대 시도 횟수
        delay: 초기 대기 시간 (초)
        backoff: 대기 시간 증가 배수
        max_delay: 최대 대기 시간
        exceptions: 재시도할 예외 타입들
        on_retry: 재시도 시 호출할 콜백 (attempt, exception, delay)
        jitter: 대기 시간에 랜덤 요소 추가 (트래픽 분산)

    사용법:
        @retry(max_attempts=3, delay=2)
        def fetch_data(url):
            ...
    """

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"[retry] {func.__name__} 최종 실패 ({attempt}/{max_attempts}): {e}"
                        )
                        raise

                    # 재시도 대기 시간 계산
                    wait_time = min(current_delay, max_delay)
                    if jitter:
                        wait_time = wait_time * (0.5 + random.random())

                    logger.warning(
                        f"[retry] {func.__name__} 실패 ({attempt}/{max_attempts}): {e}. "
                        f"{wait_time:.1f}초 후 재시도..."
                    )

                    # 콜백 호출
                    if on_retry:
                        try:
                            on_retry(attempt, e, wait_time)
                        except Exception:
                            pass

                    time.sleep(wait_time)
                    current_delay *= backoff

            # 여기 도달하면 안 됨
            raise last_exception

        return wrapper

    return decorator


def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    jitter: bool = True,
):
    """
    비동기 재시도 데코레이터

    사용법:
        @retry_async(max_attempts=3, delay=2)
        async def fetch_data_async(url):
            ...
    """
    import asyncio

    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)

                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(f"[retry_async] {func.__name__} 최종 실패: {e}")
                        raise

                    wait_time = min(current_delay, max_delay)
                    if jitter:
                        wait_time = wait_time * (0.5 + random.random())

                    logger.warning(
                        f"[retry_async] {func.__name__} 실패 ({attempt}/{max_attempts}): {e}. "
                        f"{wait_time:.1f}초 후 재시도..."
                    )

                    await asyncio.sleep(wait_time)
                    current_delay *= backoff

            raise last_exception

        return wrapper

    return decorator


def timeout_handler(timeout_seconds: float):
    """
    타임아웃 데코레이터 (스레드 기반)

    주의: 이 데코레이터는 함수를 강제 종료하지 않고,
          시간 초과 시 예외를 발생시킵니다.

    사용법:
        @timeout_handler(30)
        def slow_function():
            ...
    """
    import signal
    import platform

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Windows에서는 signal.SIGALRM을 사용할 수 없음
            if platform.system() == "Windows":
                return func(*args, **kwargs)

            def timeout_signal_handler(signum, frame):
                raise TimeoutError(f"{func.__name__} 타임아웃 ({timeout_seconds}초)")

            # 이전 핸들러 저장
            old_handler = signal.signal(signal.SIGALRM, timeout_signal_handler)
            signal.alarm(int(timeout_seconds))

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

        return wrapper

    return decorator


class CircuitBreaker:
    """
    서킷 브레이커 패턴 구현

    연속 실패 시 일시적으로 호출 차단하여 시스템 보호
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_requests: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests

        self._failures = 0
        self._last_failure_time: Optional[float] = None
        self._state = "closed"  # closed, open, half_open
        self._half_open_successes = 0

    @property
    def state(self) -> str:
        self._check_state()
        return self._state

    def _check_state(self):
        """상태 확인 및 전환"""
        if self._state == "open":
            if (
                self._last_failure_time
                and (time.time() - self._last_failure_time) >= self.recovery_timeout
            ):
                self._state = "half_open"
                self._half_open_successes = 0
                logger.info("[CircuitBreaker] half_open 상태로 전환")

    def record_failure(self, exception: Exception = None):
        """실패 기록"""
        self._failures += 1
        self._last_failure_time = time.time()

        if self._state == "half_open":
            self._state = "open"
            logger.warning("[CircuitBreaker] half_open에서 실패, open 상태로 전환")
        elif self._failures >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                f"[CircuitBreaker] 실패 임계치 도달 ({self._failures}), open 상태로 전환"
            )

    def record_success(self):
        """성공 기록"""
        if self._state == "half_open":
            self._half_open_successes += 1
            if self._half_open_successes >= self.half_open_requests:
                self._state = "closed"
                self._failures = 0
                logger.info("[CircuitBreaker] 복구 완료, closed 상태로 전환")
        else:
            self._failures = 0

    def can_execute(self) -> bool:
        """실행 가능 여부"""
        self._check_state()
        return self._state != "open"

    def __call__(self, func: Callable):
        """데코레이터로 사용"""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not self.can_execute():
                raise CrawlingError(
                    f"서킷 브레이커 활성화: {func.__name__} 호출 차단됨"
                )

            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception as e:
                self.record_failure(e)
                raise

        return wrapper


def safe_execute(func: Callable, *args, default=None, log_error: bool = True, **kwargs):
    """
    안전한 함수 실행 (예외 발생 시 기본값 반환)

    사용법:
        result = safe_execute(risky_function, arg1, arg2, default="fallback")
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_error:
            logger.error(f"[safe_execute] {func.__name__} 오류: {e}")
        return default
