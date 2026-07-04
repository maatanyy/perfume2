"""메모리 모니터링 시스템"""

import psutil
import threading
import time
import logging
import gc
import os
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class MemorySnapshot:
    """메모리 스냅샷"""

    timestamp: datetime
    rss_mb: float  # Resident Set Size (실제 물리 메모리)
    vms_mb: float  # Virtual Memory Size
    percent: float  # 시스템 메모리 사용률
    available_mb: float  # 사용 가능한 메모리


@dataclass
class MemoryStats:
    """메모리 통계"""

    current: Optional[MemorySnapshot] = None
    peak_rss_mb: float = 0
    peak_time: Optional[datetime] = None
    warning_count: int = 0
    critical_count: int = 0
    gc_count: int = 0
    history: deque = field(default_factory=lambda: deque(maxlen=60))  # 최근 60개 기록


class MemoryMonitor:
    """
    메모리 모니터링 시스템

    특징:
    - 실시간 메모리 사용량 추적
    - 임계치 도달 시 콜백 실행 (브라우저 정리 등)
    - 자동 가비지 컬렉션 트리거
    - 메모리 이력 보관
    """

    # 기본 설정 (4GB RAM 기준)
    DEFAULT_WARNING_THRESHOLD_MB = 2500  # 2.5GB 경고
    DEFAULT_CRITICAL_THRESHOLD_MB = 3200  # 3.2GB 위험
    DEFAULT_CHECK_INTERVAL = 5  # 5초마다 확인

    def __init__(
        self,
        warning_threshold_mb: float = None,
        critical_threshold_mb: float = None,
        check_interval: int = None,
        on_warning: Callable = None,
        on_critical: Callable = None,
    ):
        self.warning_threshold_mb = (
            warning_threshold_mb or self.DEFAULT_WARNING_THRESHOLD_MB
        )
        self.critical_threshold_mb = (
            critical_threshold_mb or self.DEFAULT_CRITICAL_THRESHOLD_MB
        )
        self.check_interval = check_interval or self.DEFAULT_CHECK_INTERVAL

        self._on_warning = on_warning
        self._on_critical = on_critical

        self._stats = MemoryStats()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._process = psutil.Process(os.getpid())

        logger.info(
            f"MemoryMonitor 초기화: warning={self.warning_threshold_mb}MB, "
            f"critical={self.critical_threshold_mb}MB"
        )

    def start(self):
        """모니터링 시작"""
        if self._running:
            return

        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("[MemoryMonitor] 모니터링 시작")

    def stop(self):
        """모니터링 중지"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
        logger.info("[MemoryMonitor] 모니터링 중지")

    def _get_memory_info(self) -> MemorySnapshot:
        """현재 메모리 정보 수집"""
        try:
            mem_info = self._process.memory_info()
            system_mem = psutil.virtual_memory()

            return MemorySnapshot(
                timestamp=datetime.now(),
                rss_mb=mem_info.rss / (1024 * 1024),
                vms_mb=mem_info.vms / (1024 * 1024),
                percent=system_mem.percent,
                available_mb=system_mem.available / (1024 * 1024),
            )
        except Exception as e:
            logger.error(f"메모리 정보 수집 실패: {e}")
            return None

    def _monitor_loop(self):
        """백그라운드 모니터링 루프"""
        while self._running:
            try:
                snapshot = self._get_memory_info()
                if snapshot:
                    self._process_snapshot(snapshot)
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"모니터링 루프 오류: {e}")

    def _process_snapshot(self, snapshot: MemorySnapshot):
        """스냅샷 처리"""
        with self._lock:
            self._stats.current = snapshot
            self._stats.history.append(snapshot)

            # 피크 업데이트
            if snapshot.rss_mb > self._stats.peak_rss_mb:
                self._stats.peak_rss_mb = snapshot.rss_mb
                self._stats.peak_time = snapshot.timestamp

        # 임계치 확인
        if snapshot.rss_mb >= self.critical_threshold_mb:
            self._handle_critical(snapshot)
        elif snapshot.rss_mb >= self.warning_threshold_mb:
            self._handle_warning(snapshot)

    def _handle_warning(self, snapshot: MemorySnapshot):
        """경고 상태 처리"""
        with self._lock:
            self._stats.warning_count += 1

        logger.warning(
            f"[MemoryMonitor] ⚠️ 메모리 경고: {snapshot.rss_mb:.1f}MB "
            f"(임계치: {self.warning_threshold_mb}MB)"
        )

        # 가비지 컬렉션 실행
        gc.collect()
        self._stats.gc_count += 1

        if self._on_warning:
            try:
                self._on_warning(snapshot)
            except Exception as e:
                logger.error(f"Warning 콜백 오류: {e}")

    def _handle_critical(self, snapshot: MemorySnapshot):
        """위험 상태 처리"""
        with self._lock:
            self._stats.critical_count += 1

        logger.error(
            f"[MemoryMonitor] 🚨 메모리 위험: {snapshot.rss_mb:.1f}MB "
            f"(임계치: {self.critical_threshold_mb}MB)"
        )

        # 강제 가비지 컬렉션
        gc.collect()
        gc.collect()  # 두 번 실행
        self._stats.gc_count += 2

        if self._on_critical:
            try:
                self._on_critical(snapshot)
            except Exception as e:
                logger.error(f"Critical 콜백 오류: {e}")

    def get_current_usage(self) -> Dict[str, Any]:
        """현재 메모리 사용량 반환"""
        snapshot = self._get_memory_info()
        if not snapshot:
            return {}

        return {
            "rss_mb": round(snapshot.rss_mb, 1),
            "vms_mb": round(snapshot.vms_mb, 1),
            "system_percent": round(snapshot.percent, 1),
            "available_mb": round(snapshot.available_mb, 1),
            "status": self._get_status(snapshot.rss_mb),
        }

    def _get_status(self, rss_mb: float) -> str:
        """메모리 상태 반환"""
        if rss_mb >= self.critical_threshold_mb:
            return "critical"
        elif rss_mb >= self.warning_threshold_mb:
            return "warning"
        return "normal"

    def get_stats(self) -> Dict[str, Any]:
        """통계 정보 반환"""
        with self._lock:
            current = self._stats.current
            return {
                "current_rss_mb": round(current.rss_mb, 1) if current else 0,
                "peak_rss_mb": round(self._stats.peak_rss_mb, 1),
                "peak_time": (
                    self._stats.peak_time.isoformat() if self._stats.peak_time else None
                ),
                "warning_count": self._stats.warning_count,
                "critical_count": self._stats.critical_count,
                "gc_count": self._stats.gc_count,
                "status": self._get_status(current.rss_mb if current else 0),
                "thresholds": {
                    "warning_mb": self.warning_threshold_mb,
                    "critical_mb": self.critical_threshold_mb,
                },
            }

    def get_history(self, minutes: int = 5) -> list:
        """최근 메모리 이력 반환"""
        with self._lock:
            # 분당 12개 (5초 간격)
            count = min(minutes * 12, len(self._stats.history))
            recent = list(self._stats.history)[-count:]

            return [
                {
                    "time": s.timestamp.strftime("%H:%M:%S"),
                    "rss_mb": round(s.rss_mb, 1),
                    "percent": round(s.percent, 1),
                }
                for s in recent
            ]

    def force_gc(self):
        """강제 가비지 컬렉션"""
        logger.info("[MemoryMonitor] 강제 GC 실행")
        gc.collect()
        gc.collect()
        self._stats.gc_count += 2

        # 메모리 정보 갱신
        snapshot = self._get_memory_info()
        if snapshot:
            logger.info(f"[MemoryMonitor] GC 후 메모리: {snapshot.rss_mb:.1f}MB")


# 전역 모니터 인스턴스
_memory_monitor: Optional[MemoryMonitor] = None
_monitor_lock = threading.Lock()


def get_memory_monitor(
    warning_threshold_mb: float = None,
    critical_threshold_mb: float = None,
    on_warning: Callable = None,
    on_critical: Callable = None,
) -> MemoryMonitor:
    """전역 메모리 모니터 가져오기 (싱글톤)"""
    global _memory_monitor

    with _monitor_lock:
        if _memory_monitor is None:
            _memory_monitor = MemoryMonitor(
                warning_threshold_mb=warning_threshold_mb,
                critical_threshold_mb=critical_threshold_mb,
                on_warning=on_warning,
                on_critical=on_critical,
            )
            _memory_monitor.start()
        return _memory_monitor


def shutdown_memory_monitor():
    """전역 메모리 모니터 종료"""
    global _memory_monitor

    with _monitor_lock:
        if _memory_monitor:
            _memory_monitor.stop()
            _memory_monitor = None
