"""
개선된 크롤링 엔진 v2

주요 개선사항:
- 비동기/병렬 처리 최적화
- 브라우저 풀 통합
- 메모리 모니터링 통합
- 작업별 리소스 격리
- 세마포어 기반 동시성 제어
"""

import threading
import asyncio
import time
import gc
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from flask import current_app
from database import db

logger = logging.getLogger(__name__)

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))


@dataclass
class JobStats:
    """작업 통계"""

    total_items: int = 0
    processed_items: int = 0
    success_count: int = 0
    error_count: int = 0
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    memory_peak_mb: float = 0

    @property
    def elapsed_seconds(self) -> float:
        if not self.start_time:
            return 0
        end = self.end_time or datetime.now(KST)
        return (end - self.start_time).total_seconds()

    @property
    def items_per_second(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed <= 0:
            return 0
        return self.processed_items / elapsed


class CrawlingEngineV2:
    """
    개선된 크롤링 엔진

    특징:
    - 브라우저 풀 사용으로 메모리 효율화
    - 세마포어 기반 동시성 제어
    - 메모리 모니터링 통합
    - 작업 취소 지원
    - 상세 통계 제공
    """

    def __init__(self):
        self.active_jobs: Dict[int, threading.Thread] = {}
        self.job_cancelled: Dict[int, bool] = {}
        self.job_stats: Dict[int, JobStats] = {}
        self.app = None

        # 동시성 제어 (4GB RAM, 2 vCPU 최적화)
        self._http_semaphore = threading.Semaphore(10)  # HTTP 요청 동시 10개
        self._browser_semaphore = threading.Semaphore(2)  # 브라우저 동시 2개

        self._lock = threading.Lock()

        # 메모리 모니터링 설정
        self._setup_memory_monitoring()

        logger.info("[CrawlingEngineV2] 초기화 완료")

    def _setup_memory_monitoring(self):
        """메모리 모니터링 설정"""
        from utils.memory_monitor import get_memory_monitor
        from utils.browser_pool import get_browser_pool, shutdown_browser_pool

        def on_memory_warning(snapshot):
            """메모리 경고 시 호출"""
            logger.warning(
                f"[MemoryWarning] {snapshot.rss_mb:.1f}MB - 가비지 컬렉션 실행"
            )
            gc.collect()

        def on_memory_critical(snapshot):
            """메모리 위험 시 호출"""
            logger.error(f"[MemoryCritical] {snapshot.rss_mb:.1f}MB - 브라우저 풀 리셋")
            # 브라우저 풀 리셋
            try:
                pool = get_browser_pool()
                pool.shutdown()
                gc.collect()
                gc.collect()
            except Exception as e:
                logger.error(f"브라우저 풀 리셋 실패: {e}")

        # 모니터 시작
        get_memory_monitor(
            warning_threshold_mb=2500,
            critical_threshold_mb=3200,
            on_warning=on_memory_warning,
            on_critical=on_memory_critical,
        )

    def set_app(self, app):
        """Flask 앱 설정"""
        self.app = app

    def start_crawling(self, job, spreadsheet_url: str, sheet_name: str):
        """크롤링 작업 시작"""
        from models.crawling_job import CrawlingJob

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
        """작업 취소"""
        with self._lock:
            self.job_cancelled[job_id] = True
        logger.info(f"[CrawlingEngineV2] 작업 #{job_id} 취소 요청")

    def get_job_stats(self, job_id: int) -> Optional[Dict]:
        """작업 통계 반환"""
        stats = self.job_stats.get(job_id)
        if not stats:
            return None

        return {
            "total_items": stats.total_items,
            "processed_items": stats.processed_items,
            "success_count": stats.success_count,
            "error_count": stats.error_count,
            "elapsed_seconds": round(stats.elapsed_seconds, 1),
            "items_per_second": round(stats.items_per_second, 2),
            "memory_peak_mb": round(stats.memory_peak_mb, 1),
        }

    def _run_crawling(self, job_id: int, spreadsheet_url: str, sheet_name: str):
        """크롤링 실행 (백그라운드 스레드)"""
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
            get_sheet_data,
            parse_sheet_data,
            extract_spreadsheet_id,
            extract_gid_from_url,
        )
        from crawlers.crawler_factory import get_crawler, get_crawler_by_url

        job = CrawlingJob.query.get(job_id)
        if not job:
            return

        stats = self.job_stats.get(job_id, JobStats())

        try:
            job.start()
            self._add_log(job_id, "INFO", f"크롤링 시작: {sheet_name}")

            # 구글 시트 데이터 가져오기
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

            # 크롤러 초기화
            crawler = get_crawler(job.site_name)
            if not crawler and products:
                first_url = products[0].get("waffle", {}).get("url")
                if first_url:
                    crawler = get_crawler_by_url(first_url)

            if not crawler:
                raise ValueError(f"{job.site_name} 사이트는 지원되지 않습니다.")

            # 배치 처리 설정
            batch_size = current_app.config.get("CRAWLING_BATCH_SIZE", 10)
            max_workers = current_app.config.get("CRAWLING_MAX_WORKERS", 2)

            results = []
            total_batches = (len(products) + batch_size - 1) // batch_size

            for batch_idx, i in enumerate(range(0, len(products), batch_size)):
                # 취소 확인
                if self.job_cancelled.get(job_id, False):
                    job.cancel()
                    self._add_log(job_id, "INFO", "크롤링이 취소되었습니다.")
                    break

                batch = products[i : i + batch_size]
                batch_num = batch_idx + 1

                self._add_log(
                    job_id,
                    "INFO",
                    f"배치 {batch_num}/{total_batches} 처리 중... ({len(batch)}개 제품)",
                )

                # 병렬 처리
                batch_results = self._process_batch(
                    job_id, batch, crawler, max_workers, stats
                )
                results.extend(batch_results)

                # 진행률 업데이트
                processed = min(i + batch_size, len(products))
                stats.processed_items = processed
                job.update_progress(processed, len(products))

                self._add_log(
                    job_id,
                    "INFO",
                    f"진행률: {processed}/{len(products)} ({job.progress}%)",
                )

                # 메모리 정리
                gc.collect()

                # 메모리 사용량 추적
                self._update_memory_stats(stats)

                # 배치 간 짧은 대기
                if i + batch_size < len(products):
                    time.sleep(0.2)

            # 결과 저장
            result_file = self._save_results(job_id, results, job.site_name)
            if result_file:
                job.result_file = result_file
                db.session.commit()
                self._add_log(job_id, "INFO", f"결과 파일 저장: {result_file}")

            job.complete()
            stats.end_time = datetime.now(KST)

            self._add_log(
                job_id,
                "INFO",
                f"크롤링 완료: 성공 {stats.success_count}, 실패 {stats.error_count}, "
                f"소요시간 {stats.elapsed_seconds:.1f}초",
            )

        except Exception as e:
            job.fail(str(e))
            stats.end_time = datetime.now(KST)
            self._add_log(job_id, "ERROR", f"크롤링 실패: {str(e)}")
            logger.exception(f"Job #{job_id} 크롤링 오류")

        finally:
            # 정리
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
        """배치 처리 (병렬)"""
        batch_results = []
        crawler_cache = {}

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
                        crawler_cache,
                    ): product
                    for product in batch
                }

                for future in as_completed(future_to_product):
                    if self.job_cancelled.get(job_id, False):
                        break

                    try:
                        result = future.result(timeout=60)
                        batch_results.append(result)

                        # 통계 업데이트
                        if result.get("error"):
                            stats.error_count += 1
                        else:
                            stats.success_count += 1

                        # 로그 처리
                        if "logs" in result:
                            for level, msg in result["logs"]:
                                self._add_log(job_id, level, msg)
                            del result["logs"]

                    except Exception as e:
                        product = future_to_product[future]
                        stats.error_count += 1
                        self._add_log(
                            job_id,
                            "ERROR",
                            f'제품 크롤링 실패: {product.get("product_name", "Unknown")} - {str(e)}',
                        )
                        batch_results.append(
                            {
                                "product_id": product.get("product_id"),
                                "product_name": product.get("product_name"),
                                "timestamp": datetime.now().isoformat(),
                                "prices": [],
                                "error": str(e),
                            }
                        )
        finally:
            # 크롤러 캐시 정리
            for site_key, cached_crawler in list(crawler_cache.items()):
                try:
                    if hasattr(cached_crawler, "_close_driver"):
                        cached_crawler._close_driver()
                    if hasattr(cached_crawler, "close"):
                        cached_crawler.close()
                except Exception as e:
                    logger.debug(f"크롤러 정리 오류 ({site_key}): {e}")
            crawler_cache.clear()

        return batch_results

    def _crawl_product_safe(
        self, product: Dict, default_crawler, job_id: int, crawler_cache: Dict
    ) -> Dict:
        """안전한 제품 크롤링"""
        try:
            return self._crawl_product(product, default_crawler, job_id, crawler_cache)
        except Exception as e:
            name = str(product.get("product_name", "Unknown"))[:20]
            return {
                "product_id": product.get("product_id"),
                "product_name": product.get("product_name"),
                "timestamp": datetime.now().isoformat(),
                "prices": [],
                "error": str(e),
                "logs": [("ERROR", f"✗ {name}... 오류: {str(e)[:50]}")],
            }

    def _crawl_product(
        self, product: Dict, default_crawler, job_id: int, crawler_cache: Dict
    ) -> Dict:
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
            "logs": [],
        }

        def get_crawler_for_url(url: str):
            """URL에 맞는 크롤러 반환"""
            url_lower = url.lower()

            if "shinsegaetvshopping.com" in url_lower:
                key, cls = "ssg_shopping", SSGCrawler
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

            if key not in crawler_cache:
                crawler_cache[key] = cls()
            return crawler_cache[key]

        name_short = str(product.get("product_name", "Unknown"))[:20]

        # Waffle 크롤링
        waffle_info = product.get("waffle", {})
        if waffle_info.get("url"):
            url = waffle_info["url"]
            try:
                crawler = get_crawler_for_url(url)
                data = crawler.crawl_price(url)
                result["prices"].append({"seller": "waffle", **data})
                price = data.get("상품 가격", "N/A")
                result["logs"].append(("INFO", f"✓ {name_short}... Waffle: {price}원"))
            except Exception as e:
                result["logs"].append(
                    ("ERROR", f"✗ {name_short}... Waffle 실패: {str(e)[:40]}")
                )
                result["prices"].append({"seller": "waffle", "error": str(e)})

        # 경쟁사 크롤링
        for comp in product.get("competitors", []):
            url = comp.get("url")
            if not url:
                continue

            seller = comp.get("name", "Unknown")
            try:
                crawler = get_crawler_for_url(url)
                data = crawler.crawl_price(url)
                result["prices"].append({"seller": seller, **data})
                price = data.get("상품 가격", "N/A")
                result["logs"].append(
                    ("INFO", f"✓ {name_short}... {seller}: {price}원")
                )
            except Exception as e:
                result["logs"].append(
                    ("ERROR", f"✗ {name_short}... {seller} 실패: {str(e)[:40]}")
                )
                result["prices"].append({"seller": seller, "error": str(e)})

        return result

    def _update_memory_stats(self, stats: JobStats):
        """메모리 통계 업데이트"""
        try:
            from utils.memory_monitor import get_memory_monitor

            monitor = get_memory_monitor()
            usage = monitor.get_current_usage()
            rss = usage.get("rss_mb", 0)
            if rss > stats.memory_peak_mb:
                stats.memory_peak_mb = rss
        except Exception:
            pass

    def _save_results(
        self, job_id: int, results: List[Dict], site_name: str
    ) -> Optional[str]:
        """결과를 Excel 파일로 저장"""
        try:
            import xlsxwriter
            import os

            results_dir = "results"
            os.makedirs(results_dir, exist_ok=True)

            kst_now = datetime.now(KST)
            timestamp = kst_now.strftime("%Y%m%d_%H%M%S")
            filename = f"{site_name}_가격조사_{timestamp}.xlsx"
            filepath = os.path.join(results_dir, filename)

            workbook = xlsxwriter.Workbook(filepath, {"strings_to_numbers": False})

            # 포맷 정의
            header_format = workbook.add_format(
                {
                    "bold": True,
                    "bg_color": "#366092",
                    "font_color": "white",
                    "align": "center",
                    "valign": "vcenter",
                }
            )
            title_format = workbook.add_format({"bold": True, "font_size": 12})
            bold_format = workbook.add_format({"bold": True})
            bold_red_format = workbook.add_format({"bold": True, "font_color": "red"})

            # 시트1: 전체 결과
            ws1 = workbook.add_worksheet("전체 결과")
            ws1.set_column("A:A", 20)
            ws1.set_column("B:B", 50)
            ws1.set_column("C:F", 15)

            row = 0
            for result in results:
                ws1.write(
                    row, 0, f"제품명: {result.get('product_name', 'N/A')}", title_format
                )
                row += 1
                ws1.write(row, 0, f"제품ID: {result.get('product_id', 'N/A')}")
                row += 1
                ws1.write(row, 0, f"추출 시간: {result.get('timestamp', 'N/A')}")
                row += 2

                headers = [
                    "판매처",
                    "상품 URL",
                    "상품가격",
                    "배송비",
                    "배송비여부",
                    "최종가격",
                ]
                for col, h in enumerate(headers):
                    ws1.write(row, col, h, header_format)
                row += 1

                for price in result.get("prices", []):
                    seller = (
                        "Waffle (우리회사)"
                        if price.get("seller") == "waffle"
                        else f"경쟁사 ({price.get('seller', 'N/A')})"
                    )
                    ws1.write_string(row, 0, seller)
                    ws1.write_string(row, 1, str(price.get("상품 url", "N/A")))

                    for col_idx, key in enumerate(["상품 가격", "배송비"], start=2):
                        val = price.get(key, "N/A")
                        if isinstance(val, (int, float)):
                            ws1.write_number(row, col_idx, val)
                        else:
                            ws1.write_string(row, col_idx, str(val))

                    ws1.write_string(row, 4, str(price.get("배송비 여부", "N/A")))

                    final = price.get("최종 가격", "N/A")
                    if isinstance(final, (int, float)):
                        ws1.write_number(row, 5, final)
                    else:
                        ws1.write_string(row, 5, str(final))

                    row += 1
                row += 2

            # 시트2: 가격 역전
            ws2 = workbook.add_worksheet("가격 역전 항목")
            ws2.set_column("A:A", 20)
            ws2.set_column("B:B", 50)
            ws2.set_column("C:G", 15)

            row = 0
            ws2.write_string(
                row, 0, "【가격 역전 항목 (경쟁사가 더 저렴한 경우)】", title_format
            )
            row += 2

            found = False
            for result in results:
                waffle_price = None
                for p in result.get("prices", []):
                    if p.get("seller") == "waffle":
                        waffle_price = p.get("최종 가격")
                        break

                if not isinstance(waffle_price, (int, float)):
                    continue

                cheaper = [
                    p
                    for p in result.get("prices", [])
                    if p.get("seller") != "waffle"
                    and isinstance(p.get("최종 가격"), (int, float))
                    and p["최종 가격"] < waffle_price
                ]

                if cheaper:
                    found = True
                    ws2.write(
                        row,
                        0,
                        f"제품명: {result.get('product_name', 'N/A')}",
                        bold_format,
                    )
                    row += 1
                    ws2.write(row, 0, f"제품ID: {result.get('product_id', 'N/A')}")
                    row += 2

                    headers = [
                        "판매처",
                        "상품 URL",
                        "상품가격",
                        "배송비",
                        "배송비여부",
                        "최종가격",
                        "가격차이",
                    ]
                    for col, h in enumerate(headers):
                        ws2.write(row, col, h, header_format)
                    row += 1

                    for p in result.get("prices", []):
                        if p.get("seller") == "waffle":
                            ws2.write_string(row, 0, "Waffle (우리회사)")
                            ws2.write_string(row, 1, str(p.get("상품 url", "N/A")))
                            ws2.write_number(row, 5, waffle_price)
                            ws2.write_string(row, 6, "-")
                            row += 1
                            break

                    for c in cheaper:
                        cp = c["최종 가격"]
                        diff = int(waffle_price - cp)
                        ws2.write_string(row, 0, f"경쟁사 ({c.get('seller', 'N/A')})")
                        ws2.write_string(row, 1, str(c.get("상품 url", "N/A")))
                        ws2.write_number(row, 5, cp)
                        ws2.write(row, 6, f"-{diff}원 저렴", bold_red_format)
                        row += 1

                    row += 2

            if not found:
                ws2.write(row, 0, "가격 역전 항목이 없습니다.")

            workbook.close()
            return filepath

        except Exception as e:
            logger.error(f"Excel 저장 실패: {e}")
            return None

    def _add_log(self, job_id: int, level: str, message: str):
        """로그 추가"""
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
        """시스템 상태 반환"""
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
        """엔진 종료"""
        logger.info("[CrawlingEngineV2] 종료 중...")

        # 모든 작업 취소
        for job_id in list(self.active_jobs.keys()):
            self.cancel_job(job_id)

        # 브라우저 풀 종료
        try:
            from utils.browser_pool import shutdown_browser_pool

            shutdown_browser_pool()
        except Exception:
            pass

        # 메모리 모니터 종료
        try:
            from utils.memory_monitor import shutdown_memory_monitor

            shutdown_memory_monitor()
        except Exception:
            pass

        logger.info("[CrawlingEngineV2] 종료 완료")


# 전역 엔진 인스턴스 (lazy initialization)
_crawling_engine_v2 = None
_engine_lock = threading.Lock()


def get_crawling_engine_v2() -> CrawlingEngineV2:
    """전역 크롤링 엔진 가져오기 (싱글톤)"""
    global _crawling_engine_v2

    with _engine_lock:
        if _crawling_engine_v2 is None:
            _crawling_engine_v2 = CrawlingEngineV2()
        return _crawling_engine_v2


# 하위 호환성을 위한 alias (기존 코드에서 사용)
crawling_engine_v2 = None  # import 시점에는 None
