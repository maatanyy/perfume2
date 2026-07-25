"""
개선된 크롤링 엔진 v2 (perfume3)

주요 개선사항:
- SSE(Server-Sent Events) 실시간 진행률 push
- 브라우저 세마포어 5개로 확장 (5개 사이트 동시 처리)
- 결과 상태 4분류: success / sold_out / not_found / error
- 모든 URL 결과 빠짐없이 기록
- 아이템 단위 진행률 업데이트 (배치 단위 → 개별 아이템)
- ETA 계산 제공
"""

import threading
import queue
import time
import gc
import json
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from flask import current_app
from database import db

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

# 스레드 로컬 스토리지
_thread_local = threading.local()


def _get_thread_crawler_cache():
    if not hasattr(_thread_local, "crawler_cache"):
        _thread_local.crawler_cache = {}
    return _thread_local.crawler_cache


def _clear_thread_crawler_cache():
    if hasattr(_thread_local, "crawler_cache"):
        for site_key, crawler in list(_thread_local.crawler_cache.items()):
            try:
                if hasattr(crawler, "_close_driver"):
                    crawler._close_driver()
            except Exception as e:
                logger.debug(f"Error closing thread-local crawler {site_key}: {e}")
        _thread_local.crawler_cache.clear()


@dataclass
class JobStats:
    """작업 통계"""
    total_items: int = 0
    processed_items: int = 0
    success_count: int = 0
    sold_out_count: int = 0
    not_found_count: int = 0
    error_count: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    memory_peak_mb: float = 0
    # 최근 N개 아이템 완료 시각 (rolling window용)
    _recent_completions: list = field(default_factory=list)

    def record_completion(self):
        """아이템 완료 시각 기록 (rolling average 계산용)"""
        now = time.time()
        self._recent_completions.append(now)
        # 최근 20개만 유지
        if len(self._recent_completions) > 20:
            self._recent_completions = self._recent_completions[-20:]

    @property
    def elapsed_seconds(self) -> float:
        if not self.start_time:
            return 0
        end = self.end_time or datetime.now(KST)
        return (end - self.start_time).total_seconds()

    @property
    def items_per_second(self) -> float:
        # 최근 10개 이상 있으면 rolling average 사용 (Chrome cold start 영향 제거)
        if len(self._recent_completions) >= 5:
            window = self._recent_completions[-10:]
            if len(window) >= 2:
                span = window[-1] - window[0]
                if span > 0:
                    return (len(window) - 1) / span
        # 초반엔 전체 평균
        elapsed = self.elapsed_seconds
        if elapsed <= 0 or self.processed_items == 0:
            return 0
        return self.processed_items / elapsed

    def eta_seconds(self) -> Optional[float]:
        """예상 남은 시간(초) 계산"""
        remaining = self.total_items - self.processed_items
        if remaining <= 0:
            return 0
        speed = self.items_per_second
        if speed <= 0:
            return None
        return remaining / speed

    def eta_display(self) -> str:
        """예상 완료 시간 표시용 문자열"""
        if self.processed_items < 3:
            return "계산 중..."
        eta = self.eta_seconds()
        if eta is None:
            return "계산 중..."
        if eta <= 0:
            return "완료 직전"
        minutes = int(eta // 60)
        seconds = int(eta % 60)
        if minutes > 0:
            return f"약 {minutes}분 {seconds}초"
        return f"약 {seconds}초"


class CrawlingEngineV2:
    """개선된 크롤링 엔진 - SSE 실시간 진행률, 5-site 동시 처리"""

    def __init__(self):
        self.active_jobs: Dict[int, threading.Thread] = {}
        self.job_cancelled: Dict[int, bool] = {}
        self.job_stats: Dict[int, JobStats] = {}
        self.app = None

        # 브라우저 세마포어: 2-core 서버에서 동시 Chrome 최대 3개로 제한
        # (5사이트 × 5workers = 25 Chrome이 동시 실행되면 CPU 포화)
        self._http_semaphore = threading.Semaphore(10)
        self._browser_semaphore = threading.Semaphore(3)

        self._lock = threading.Lock()

        # ★ SSE 큐: job_id → Queue (실시간 진행률 스트리밍)
        self._sse_queues: Dict[int, queue.Queue] = {}
        self._sse_lock = threading.Lock()

        self._setup_memory_monitoring()
        logger.info("[CrawlingEngineV2] 초기화 완료 (브라우저 세마포어: 5)")

    def _setup_memory_monitoring(self):
        from utils.memory_monitor import get_memory_monitor
        from utils.browser_pool import get_browser_pool, shutdown_browser_pool

        def on_memory_warning(snapshot):
            logger.warning(f"[MemoryWarning] {snapshot.rss_mb:.1f}MB - 가비지 컬렉션 실행")
            gc.collect()

        def on_memory_critical(snapshot):
            logger.error(f"[MemoryCritical] {snapshot.rss_mb:.1f}MB - 브라우저 풀 리셋")
            try:
                pool = get_browser_pool()
                pool.shutdown()
                gc.collect()
                gc.collect()
            except Exception as e:
                logger.error(f"브라우저 풀 리셋 실패: {e}")

        get_memory_monitor(
            warning_threshold_mb=2500,
            critical_threshold_mb=3200,
            on_warning=on_memory_warning,
            on_critical=on_memory_critical,
        )

    def set_app(self, app):
        self.app = app

    # =========================================================
    # SSE 큐 관리
    # =========================================================

    def create_sse_queue(self, job_id: int) -> queue.Queue:
        """SSE 스트리밍용 큐 생성"""
        q = queue.Queue(maxsize=200)
        with self._sse_lock:
            self._sse_queues[job_id] = q
        return q

    def remove_sse_queue(self, job_id: int):
        """SSE 큐 제거"""
        with self._sse_lock:
            self._sse_queues.pop(job_id, None)

    def _push_sse(self, job_id: int, data: dict):
        """SSE 큐에 진행률 데이터 push (구독자 없으면 무시)"""
        with self._sse_lock:
            q = self._sse_queues.get(job_id)
        if q:
            try:
                q.put_nowait(data)
            except queue.Full:
                pass  # 큐가 꽉 차면 드랍 (블로킹 방지)

    def _push_sse_complete(self, job_id: int):
        """SSE 완료 신호 전송"""
        with self._sse_lock:
            q = self._sse_queues.get(job_id)
        if q:
            try:
                q.put_nowait(None)  # None = sentinel (스트림 종료)
            except queue.Full:
                pass

    # =========================================================
    # 작업 시작 / 취소
    # =========================================================

    def start_crawling(self, job, spreadsheet_url: str, sheet_name: str):
        """크롤링 작업 시작"""
        thread = threading.Thread(
            target=self._run_crawling,
            args=(job.id, spreadsheet_url, sheet_name),
            daemon=True,
            name=f"crawling-job-{job.id}",
        )
        with self._lock:
            self.active_jobs[job.id] = thread
            self.job_cancelled[job.id] = False
            self.job_stats[job.id] = JobStats(start_time=datetime.now(KST))
        thread.start()
        logger.info(f"[CrawlingEngineV2] 작업 #{job.id} 시작")

    def cancel_job(self, job_id: int):
        with self._lock:
            self.job_cancelled[job_id] = True
        logger.info(f"[CrawlingEngineV2] 작업 #{job_id} 취소 요청")

        # Chrome 프로세스 강제 종료
        try:
            import psutil, signal
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    name = (proc.info.get('name') or '').lower()
                    cmdline = ' '.join(proc.info.get('cmdline') or []).lower()
                    if 'chrome' in name or 'chromium' in name or 'chromedriver' in name:
                        proc.send_signal(signal.SIGKILL)
                        logger.info(f"[Cancel] Chrome 프로세스 강제 종료: PID {proc.pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.warning(f"[Cancel] Chrome 강제 종료 실패: {e}")

    def get_job_stats(self, job_id: int) -> Optional[Dict]:
        stats = self.job_stats.get(job_id)
        if not stats:
            return None
        return {
            "total_items": stats.total_items,
            "processed_items": stats.processed_items,
            "success_count": stats.success_count,
            "sold_out_count": stats.sold_out_count,
            "not_found_count": stats.not_found_count,
            "error_count": stats.error_count,
            "elapsed_seconds": round(stats.elapsed_seconds, 1),
            "items_per_second": round(stats.items_per_second, 2),
            "eta_display": stats.eta_display(),
            "memory_peak_mb": round(stats.memory_peak_mb, 1),
        }

    # =========================================================
    # 크롤링 실행
    # =========================================================

    def _run_crawling(self, job_id: int, spreadsheet_url: str, sheet_name: str):
        from app import create_app
        if self.app:
            with self.app.app_context():
                self._do_crawling(job_id, spreadsheet_url, sheet_name)
        else:
            app = create_app()
            with app.app_context():
                self._do_crawling(job_id, spreadsheet_url, sheet_name)

    def _do_crawling(self, job_id: int, spreadsheet_url: str, sheet_name: str):
        """실제 크롤링 작업"""
        from models.crawling_job import CrawlingJob
        from models.crawling_log import CrawlingLog
        from utils.google_sheets import (
            get_sheet_data, parse_sheet_data,
            extract_spreadsheet_id, extract_gid_from_url,
        )
        from crawlers.crawler_factory import get_crawler, get_crawler_by_url

        job = CrawlingJob.query.get(job_id)
        if not job:
            return

        stats = self.job_stats.get(job_id, JobStats())

        try:
            job.start()
            self._add_log(job_id, "INFO", f"크롤링 시작: {sheet_name}")

            self._add_log(job_id, "INFO", "구글 시트 데이터 읽기 중...")
            spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
            if not spreadsheet_id:
                raise ValueError("구글 시트 ID를 추출할 수 없습니다.")

            gid = extract_gid_from_url(spreadsheet_url)
            values = get_sheet_data(spreadsheet_id, sheet_name, gid)
            products = parse_sheet_data(values)

            if not products:
                raise ValueError("크롤링할 제품이 없습니다.")

            stats.total_items = len(products)
            job.total_items = len(products)
            job.processed_items = 0
            db.session.commit()

            self._add_log(job_id, "INFO", f"총 {len(products)}개 제품 발견")

            crawler = get_crawler(job.site_name)
            if not crawler and products:
                first_url = products[0].get("waffle", {}).get("url")
                if first_url:
                    crawler = get_crawler_by_url(first_url)

            if not crawler:
                raise ValueError(f"{job.site_name} 사이트는 지원되지 않습니다.")

            batch_size = current_app.config.get("CRAWLING_BATCH_SIZE", 10)
            # CJ(Selenium)는 4 workers, HTTP 사이트는 5 workers
            selenium_sites = {"cj", "cjonstyle"}
            if job.site_name.lower() in selenium_sites or getattr(crawler, "use_selenium", False):
                max_workers = 4
            else:
                max_workers = 5

            results = []
            total_batches = (len(products) + batch_size - 1) // batch_size

            for batch_idx, i in enumerate(range(0, len(products), batch_size)):
                if self.job_cancelled.get(job_id, False):
                    job.cancel()
                    self._add_log(job_id, "INFO", "크롤링이 취소되었습니다.")
                    break

                batch = products[i: i + batch_size]
                batch_num = batch_idx + 1

                self._add_log(
                    job_id, "INFO",
                    f"배치 {batch_num}/{total_batches} 처리 중... ({len(batch)}개 제품)",
                )

                batch_results = self._process_batch(
                    job_id, batch, crawler, max_workers, stats
                )
                results.extend(batch_results)

                gc.collect()
                self._update_memory_stats(stats)

                if i + batch_size < len(products):
                    time.sleep(0.1)

            # 일시 차단 등으로 error가 된 URL 재시도 (취소된 잡은 건너뜀)
            if not self.job_cancelled.get(job_id, False):
                self._retry_failed_prices(job_id, results, stats)

            # 결과 저장
            result_file = self._save_results(job_id, results, job.site_name)
            if result_file:
                job.result_file = result_file
                db.session.commit()
                self._add_log(job_id, "INFO", f"결과 파일 저장: {result_file}")

            job.complete()
            stats.end_time = datetime.now(KST)

            self._add_log(
                job_id, "INFO",
                f"크롤링 완료: 성공 {stats.success_count}, 품절 {stats.sold_out_count}, "
                f"추출실패 {stats.not_found_count}, 오류 {stats.error_count}, "
                f"소요시간 {stats.elapsed_seconds:.1f}초",
            )

            # SSE 완료 신호
            self._push_sse_complete(job_id)

        except Exception as e:
            job.fail(str(e))
            stats.end_time = datetime.now(KST)
            self._add_log(job_id, "ERROR", f"크롤링 실패: {str(e)}")
            logger.exception(f"Job #{job_id} 크롤링 오류")
            self._push_sse_complete(job_id)

        finally:
            # Chrome 프로세스 강제 종료 (좀비 방지)
            try:
                import psutil, signal
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        name = (proc.info.get('name') or '').lower()
                        if 'chrome' in name or 'chromium' in name or 'chromedriver' in name:
                            proc.send_signal(signal.SIGKILL)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
            except Exception as e:
                logger.warning(f"[Cleanup] Chrome 정리 실패: {e}")

            _clear_thread_crawler_cache()
            with self._lock:
                self.active_jobs.pop(job_id, None)
                self.job_cancelled.pop(job_id, None)
            gc.collect()

    def _process_batch(
        self,
        job_id: int,
        batch: List[Dict],
        default_crawler,
        max_workers: int,
        stats: JobStats,
    ) -> List[Dict]:
        """배치 병렬 처리 - 각 아이템 완료 시 SSE push"""
        batch_results = []

        try:
            with ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix=f"job-{job_id}"
            ) as executor:
                future_to_product = {
                    executor.submit(
                        self._crawl_product_safe,
                        product,
                        default_crawler,
                        job_id,
                        None,
                    ): product
                    for product in batch
                }

                for future in as_completed(future_to_product):
                    if self.job_cancelled.get(job_id, False):
                        break

                    try:
                        result = future.result(timeout=120)
                        batch_results.append(result)

                        # ★ 결과 상태 4분류 카운팅
                        result_status = result.get("result_status", "error")
                        if result_status == "success":
                            stats.success_count += 1
                        elif result_status == "sold_out":
                            stats.sold_out_count += 1
                        elif result_status == "not_found":
                            stats.not_found_count += 1
                        else:
                            stats.error_count += 1

                        # ★ 아이템 단위 진행률 업데이트
                        stats.processed_items += 1
                        stats.record_completion()
                        self._update_job_progress(job_id, stats)

                        # ★ SSE push (아이템 완료마다)
                        self._push_item_progress(job_id, stats, result)

                        if "logs" in result:
                            for level, msg in result["logs"]:
                                self._add_log(job_id, level, msg)
                            del result["logs"]

                    except Exception as e:
                        product = future_to_product[future]
                        stats.error_count += 1
                        stats.processed_items += 1
                        stats.record_completion()
                        self._update_job_progress(job_id, stats)

                        err_result = {
                            "product_id": product.get("product_id"),
                            "product_name": product.get("product_name"),
                            "timestamp": datetime.now().isoformat(),
                            "prices": [],
                            "result_status": "error",
                            "error": str(e),
                        }
                        batch_results.append(err_result)
                        self._push_item_progress(job_id, stats, err_result)

                        self._add_log(
                            job_id, "ERROR",
                            f'제품 크롤링 실패: {product.get("product_name", "Unknown")} - {str(e)}',
                        )
        finally:
            pass

        return batch_results

    def _retry_failed_prices(self, job_id: int, results: List[Dict], stats: JobStats):
        """error 상태 URL을 잡 말미에 한 번 더 시도한다.

        실전(2026-07-25): 롯데 45건이 크롤링 도중 일시 403으로 error였지만
        시간이 지나 재시도하면 전부 성공 — 잡이 끝나기 전에 회복시킨다.
        순차 실행이라 사이트별 요청 간격/냉각을 자연스럽게 존중한다.
        """
        from crawlers import crawler_factory

        targets = []
        for result in results:
            for entry in result.get("prices", []):
                if entry.get("결과 상태") == "error" and entry.get("상품 url"):
                    targets.append(entry)
        if not targets:
            return

        self._add_log(job_id, "INFO", f"오류 {len(targets)}건 재시도 패스 시작")
        recovered = 0
        for entry in targets:
            if self.job_cancelled.get(job_id, False):
                break
            url = entry["상품 url"]
            try:
                crawler = crawler_factory.get_crawler_by_url(url)
                if crawler is None:
                    continue
                data = crawler.crawl_price(url)
            except Exception as e:
                logger.debug(f"재시도 실패 {url[:60]}: {e}")
                continue
            new_status = data.get("결과 상태", "error")
            if new_status == "error":
                continue
            seller = entry.get("seller")
            entry.clear()
            entry.update({"seller": seller, **data, "결과 상태": new_status})
            stats.error_count = max(0, stats.error_count - 1)
            if new_status == "success":
                stats.success_count += 1
            elif new_status == "sold_out":
                stats.sold_out_count += 1
            else:
                stats.not_found_count += 1
            recovered += 1
        self._add_log(
            job_id, "INFO", f"재시도 패스 완료: {recovered}/{len(targets)}건 회복"
        )

    def _update_job_progress(self, job_id: int, stats: JobStats):
        """DB 진행률 업데이트"""
        from models.crawling_job import CrawlingJob
        try:
            job = CrawlingJob.query.get(job_id)
            if job:
                job.update_progress(stats.processed_items, stats.total_items)
        except Exception as e:
            logger.debug(f"진행률 DB 업데이트 실패: {e}")

    def _push_item_progress(self, job_id: int, stats: JobStats, result: dict):
        """SSE에 아이템별 진행률 push"""
        name = result.get("product_name", "")[:15]
        prices = result.get("prices", [])
        status = result.get("result_status", "error")

        # 마지막 처리 아이템 요약
        if prices:
            first_price = prices[0]
            price_val = first_price.get("상품 가격")
            last_item_desc = f"{name} - {price_val:,}원" if isinstance(price_val, int) else f"{name} - {status}"
        else:
            last_item_desc = f"{name} - {status}"

        percent = round((stats.processed_items / stats.total_items * 100), 1) if stats.total_items > 0 else 0

        self._push_sse(job_id, {
            "processed": stats.processed_items,
            "total": stats.total_items,
            "percent": percent,
            "eta_display": stats.eta_display(),
            "speed": round(stats.items_per_second, 2),
            "last_item": last_item_desc,
            "success": stats.success_count,
            "sold_out": stats.sold_out_count,
            "not_found": stats.not_found_count,
            "error": stats.error_count,
        })

    def _crawl_product_safe(self, product, default_crawler, job_id, crawler_cache):
        try:
            return self._crawl_product(product, default_crawler, job_id, crawler_cache)
        except Exception as e:
            name = str(product.get("product_name", "Unknown"))[:20]
            return {
                "product_id": product.get("product_id"),
                "product_name": product.get("product_name"),
                "timestamp": datetime.now().isoformat(),
                "prices": [],
                "result_status": "error",
                "error": str(e),
                "logs": [("ERROR", f"✗ {name}... 오류: {str(e)[:50]}")],
            }

    def _crawl_product(self, product, default_crawler, job_id, crawler_cache):
        """단일 제품 크롤링"""
        from crawlers.ssg_crawler import SSGCrawler
        from crawlers.cj_crawler import CJCrawler
        from crawlers.shinsegae_crawler import ShinsegaeCrawler
        from crawlers.lotte_crawler import LotteCrawler
        from crawlers.gs_crawler import GSCrawler

        result = {
            "product_id": product.get("product_id"),
            "product_name": product.get("product_name"),
            "timestamp": datetime.now().isoformat(),
            "prices": [],
            "result_status": "success",  # 전체 결과 상태 (하나라도 성공이면 success)
            "logs": [],
        }

        def get_crawler_for_url(url: str):
            url_lower = url.lower()
            if "shinsegaetvshopping.com" in url_lower:
                key, cls = "shinsegae_tv", ShinsegaeCrawler
            elif "ssg.com" in url_lower:
                key, cls = "ssg", SSGCrawler
            elif "cjonstyle.com" in url_lower:
                key, cls = "cj", CJCrawler
            elif "shinsegae" in url_lower:
                key, cls = "shinsegae", ShinsegaeCrawler
            elif "lotte" in url_lower:
                key, cls = "lotte", LotteCrawler
            elif "gsshop.com" in url_lower:
                key, cls = "gs", GSCrawler
            else:
                key, cls = "default", lambda: default_crawler

            local_cache = _get_thread_crawler_cache()
            if key not in local_cache:
                local_cache[key] = cls()
            return local_cache[key]

        name_short = str(product.get("product_name", "Unknown"))[:20]

        all_statuses = []

        def crawl_url_with_semaphore(url: str, seller: str):
            """URL 크롤링 - Selenium 크롤러는 브라우저 세마포어 사용"""
            crawler = get_crawler_for_url(url)
            if getattr(crawler, "use_selenium", False):
                with self._browser_semaphore:
                    return crawler.crawl_price(url)
            else:
                with self._http_semaphore:
                    return crawler.crawl_price(url)

        # Waffle 크롤링
        waffle_info = product.get("waffle", {})
        waffle_url = waffle_info.get("url", "").strip()
        if waffle_url:
            try:
                data = crawl_url_with_semaphore(waffle_url, "waffle")
                item_status = data.get("결과 상태", "success" if data.get("상품 가격") else "not_found")
                data["결과 상태"] = item_status
                result["prices"].append({"seller": "waffle", **data})
                all_statuses.append(item_status)
                price = data.get("상품 가격", "N/A")
                result["logs"].append(("INFO", f"✓ {name_short}... Waffle: {price}원" if isinstance(price, int) else f"✓ {name_short}... Waffle: {item_status}"))
            except Exception as e:
                result["prices"].append({"seller": "waffle", "상품 url": waffle_url, "결과 상태": "error", "에러 발생": str(e)})
                all_statuses.append("error")
                result["logs"].append(("ERROR", f"✗ {name_short}... Waffle 실패: {str(e)[:40]}"))
        else:
            # ★ URL이 없어도 기록 (누락 방지)
            result["prices"].append({"seller": "waffle", "상품 url": "", "결과 상태": "error", "에러 발생": "URL 없음"})
            all_statuses.append("error")

        # 경쟁사 크롤링
        for comp in product.get("competitors", []):
            url = comp.get("url", "").strip()
            seller = comp.get("name", "Unknown")

            if not url:
                # ★ URL이 없어도 빈 결과 기록 (누락 방지)
                result["prices"].append({"seller": seller, "상품 url": "", "결과 상태": "error", "에러 발생": "URL 없음"})
                all_statuses.append("error")
                continue

            try:
                data = crawl_url_with_semaphore(url, seller)
                item_status = data.get("결과 상태", "success" if data.get("상품 가격") else "not_found")
                data["결과 상태"] = item_status
                result["prices"].append({"seller": seller, **data})
                all_statuses.append(item_status)
                price = data.get("상품 가격", "N/A")
                result["logs"].append(("INFO", f"✓ {name_short}... {seller}: {price}원" if isinstance(price, int) else f"✓ {name_short}... {seller}: {item_status}"))
            except Exception as e:
                result["prices"].append({"seller": seller, "상품 url": url, "결과 상태": "error", "에러 발생": str(e)})
                all_statuses.append("error")
                result["logs"].append(("ERROR", f"✗ {name_short}... {seller} 실패: {str(e)[:40]}"))

        # 전체 결과 상태 결정
        if "success" in all_statuses:
            result["result_status"] = "success"
        elif "sold_out" in all_statuses:
            result["result_status"] = "sold_out"
        elif "not_found" in all_statuses:
            result["result_status"] = "not_found"
        else:
            result["result_status"] = "error"

        return result

    def _update_memory_stats(self, stats: JobStats):
        try:
            from utils.memory_monitor import get_memory_monitor
            monitor = get_memory_monitor()
            usage = monitor.get_current_usage()
            rss = usage.get("rss_mb", 0)
            if rss > stats.memory_peak_mb:
                stats.memory_peak_mb = rss
        except Exception:
            pass

    def _save_results(self, job_id: int, results: List[Dict], site_name: str) -> Optional[str]:
        """결과를 플랫 테이블 Excel로 저장 (utils/excel_report.py에 위임)"""
        from utils.excel_report import save_results_excel
        return save_results_excel(results, site_name)

    def _add_log(self, job_id: int, level: str, message: str):
        from models.crawling_log import CrawlingLog
        try:
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            else:
                message = str(message).encode("utf-8", errors="replace").decode("utf-8")
            log = CrawlingLog(job_id=job_id, level=level, message=message)
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            logger.error(f"로그 추가 실패: {e}")
            db.session.rollback()

    def get_system_status(self) -> Dict[str, Any]:
        from utils.memory_monitor import get_memory_monitor
        from utils.browser_pool import get_browser_pool
        try:
            memory = get_memory_monitor().get_stats()
        except Exception:
            memory = {}
        try:
            browser = get_browser_pool().get_stats()
        except Exception:
            browser = {}
        return {
            "active_jobs": len(self.active_jobs),
            "job_ids": list(self.active_jobs.keys()),
            "memory": memory,
            "browser_pool": browser,
        }

    def shutdown(self):
        logger.info("[CrawlingEngineV2] 종료 중...")
        for job_id in list(self.active_jobs.keys()):
            self.cancel_job(job_id)
        try:
            from utils.browser_pool import shutdown_browser_pool
            shutdown_browser_pool()
        except Exception:
            pass
        try:
            from utils.memory_monitor import shutdown_memory_monitor
            shutdown_memory_monitor()
        except Exception:
            pass
        logger.info("[CrawlingEngineV2] 종료 완료")


# 싱글톤
_crawling_engine_v2 = None
_engine_lock = threading.Lock()

crawling_engine_v2 = None  # app.py에서 참조용


def get_crawling_engine_v2() -> CrawlingEngineV2:
    global _crawling_engine_v2, crawling_engine_v2
    with _engine_lock:
        if _crawling_engine_v2 is None:
            _crawling_engine_v2 = CrawlingEngineV2()
            crawling_engine_v2 = _crawling_engine_v2
    return _crawling_engine_v2
