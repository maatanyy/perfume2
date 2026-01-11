"""크롤링 엔진"""

import threading
from typing import List, Dict
from flask import current_app
from database import db
from app import create_app
from models.crawling_job import CrawlingJob
from models.crawling_log import CrawlingLog
from crawlers.crawler_factory import get_crawler, get_crawler_by_url

# 스레드 로컬 스토리지 (각 스레드가 독립 크롤러 캐시 보유)
thread_local = threading.local()
from utils.google_sheets import get_sheet_data, parse_sheet_data, extract_spreadsheet_id
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))


class CrawlingEngine:
    """크롤링 엔진 (Threading 방식)"""

    def __init__(self):
        self.active_jobs = {}  # job_id -> thread
        self.job_cancelled = {}  # job_id -> bool
        self.app = None  # Flask 앱 인스턴스 저장

    def set_app(self, app):
        """Flask 앱 설정 (스레드에서 사용하기 위해)"""
        self.app = app

    def start_crawling(self, job: CrawlingJob, spreadsheet_url: str, sheet_name: str):
        """크롤링 작업 시작"""
        thread = threading.Thread(
            target=self._run_crawling,
            args=(job.id, spreadsheet_url, sheet_name),
            daemon=True,
        )
        self.active_jobs[job.id] = thread
        self.job_cancelled[job.id] = False
        thread.start()

    def cancel_job(self, job_id: int):
        """작업 취소"""
        self.job_cancelled[job_id] = True

    def _run_crawling(self, job_id: int, spreadsheet_url: str, sheet_name: str):
        """크롤링 실행 (백그라운드 스레드)"""
        # Flask 앱 컨텍스트 설정 (스레드에서는 자동으로 설정되지 않음)
        if self.app:
            with self.app.app_context():
                self._do_crawling(job_id, spreadsheet_url, sheet_name)
        else:
            # 앱이 설정되지 않은 경우 새로 생성
            app = create_app()
            with app.app_context():
                self._do_crawling(job_id, spreadsheet_url, sheet_name)

    def _do_crawling(self, job_id: int, spreadsheet_url: str, sheet_name: str):
        """실제 크롤링 작업 (앱 컨텍스트 내에서 실행)"""
        from utils.google_sheets import extract_gid_from_url

        job = CrawlingJob.query.get(job_id)
        if not job:
            return

        try:
            job.start()
            self._add_log(job_id, "INFO", f"크롤링 시작: {sheet_name}")

            # 구글 시트에서 데이터 가져오기
            self._add_log(job_id, "INFO", "구글 시트 데이터 읽기 중...")
            spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
            if not spreadsheet_id:
                raise ValueError("구글 시트 ID를 추출할 수 없습니다.")

            # GID 추출 (시트 ID)
            gid = extract_gid_from_url(spreadsheet_url)

            values = get_sheet_data(spreadsheet_id, sheet_name, gid)
            products = parse_sheet_data(values)
            self._add_log(
                job_id, "INFO", f"구글 시트에서 {len(products)}개 제품 파싱 완료"
            )

            if len(products) == 0:
                raise ValueError("크롤링할 제품이 없습니다.")

            job.total_items = len(products)
            job.processed_items = 0
            db.session.commit()

            self._add_log(job_id, "INFO", f"총 {len(products)}개 제품 발견")

            # 크롤러 가져오기 (사이트명 또는 URL 기반)
            self._add_log(job_id, "INFO", f"크롤러 초기화: {job.site_name}")
            crawler = get_crawler(job.site_name)
            if not crawler:
                # URL에서 사이트 감지 시도
                self._add_log(
                    job_id,
                    "WARNING",
                    "사이트명으로 크롤러를 찾을 수 없습니다. URL에서 감지 시도...",
                )
                if job.google_sheet_url:
                    # 첫 번째 제품 URL로 사이트 감지
                    if products and products[0].get("waffle", {}).get("url"):
                        first_url = products[0]["waffle"]["url"]
                        crawler = get_crawler_by_url(first_url)
                        if crawler:
                            self._add_log(job_id, "INFO", "URL 기반 크롤러 감지 성공")

                if not crawler:
                    raise ValueError(f"{job.site_name} 사이트는 지원되지 않습니다.")

            results = []
            batch_size = 5  # 배치 크기 (메모리 최적화: 10 -> 5)
            max_workers = 2  # 병렬 처리 워커 수 (메모리 최적화: 3 -> 2)

            # 배치 레벨 크롤러 캐시는 위에서 이미 초기화됨

            for i in range(0, len(products), batch_size):
                if self.job_cancelled.get(job_id, False):
                    job.cancel()
                    self._add_log(job_id, "INFO", "크롤링이 취소되었습니다.")
                    # 캐시된 크롤러 정리
                    for cached_crawler in batch_crawler_cache.values():
                        try:
                            cached_crawler._close_driver()
                        except:
                            pass
                    return

                batch = products[i : i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (len(products) + batch_size - 1) // batch_size
                self._add_log(
                    job_id,
                    "INFO",
                    f"배치 {batch_num}/{total_batches} 처리 중... ({len(batch)}개 제품)",
                )
                batch_results = []

                # 매 배치마다 새 ThreadPoolExecutor 생성 → Chrome 폭발 방지 위해 1개만
                executor = ThreadPoolExecutor(max_workers=1)
                try:
                    future_to_product = {
                        executor.submit(
                            self._crawl_product_safe,
                            product,
                            crawler,
                            job_id,
                        ): product
                        for product in batch
                    }

                    for future in as_completed(future_to_product):
                        if self.job_cancelled.get(job_id, False):
                            break

                        try:
                            result = future.result()
                            batch_results.append(result)

                            # 워커 스레드에서 수집한 로그를 메인 스레드에서 DB에 추가
                            if "logs" in result:
                                for log_level, log_message in result["logs"]:
                                    self._add_log(job_id, log_level, log_message)
                                # 로그를 DB에 추가한 후 결과에서 제거
                                del result["logs"]

                        except Exception as e:
                            product = future_to_product[future]
                            self._add_log(
                                job_id,
                                "ERROR",
                                f'제품 크롤링 실패: {product["product_name"]} - {str(e)}',
                            )
                            batch_results.append(
                                {
                                    "product_id": product["product_id"],
                                    "product_name": product["product_name"],
                                    "timestamp": datetime.now().isoformat(),
                                    "prices": [],
                                    "error": str(e),
                                }
                            )
                finally:
                    # ThreadPoolExecutor 명시적 종료 (스레드 완전 종료 보장)
                    executor.shutdown(wait=True)
                    del executor

                results.extend(batch_results)

                # 배치 완료 후 강제 가비지 컬렉션
                import gc

                gc.collect()

                self._add_log(
                    job_id, "INFO", f"✅ 배치 {batch_num} 완료 (스레드 종료됨)"
                )
                # 명시적 정리는 finally 블록에서 수행

                # 진행률 업데이트
                processed = min(i + batch_size, len(products))
                job.update_progress(processed, len(products))
                self._add_log(
                    job_id,
                    "INFO",
                    f"진행률: {processed}/{len(products)} ({job.progress}%)",
                )

                if i + batch_size < len(products):
                    time.sleep(0.2)  # 배치 간 대기 시간 단축 (0.3 -> 0.2)

            # 모든 배치 완료 후 크롤러 정리
            for cached_crawler in batch_crawler_cache.values():
                try:
                    cached_crawler._close_driver()
                except:
                    pass

            # 결과 저장 (Excel 파일 생성)
            result_file = self._save_results(job_id, results, job.site_name)
            if result_file:
                job.result_file = result_file
                db.session.commit()
                self._add_log(job_id, "INFO", f"결과 파일 저장: {result_file}")

            job.complete()
            self._add_log(job_id, "INFO", f"크롤링 완료: {len(results)}개 결과")

        except Exception as e:
            job.fail(str(e))
            self._add_log(job_id, "ERROR", f"크롤링 실패: {str(e)}")
        finally:
            # 스레드 로컬 크롤러 정리 (메인 스레드에서 실행, 워커 스레드는 종료됨)
            # 워커 스레드들은 ThreadPoolExecutor가 종료되면서 자동 정리

            # 작업 정리
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]
            if job_id in self.job_cancelled:
                del self.job_cancelled[job_id]

    def _crawl_product(
        self, product: Dict, default_crawler, job_id: int, crawler_cache: Dict = None
    ) -> Dict:
        """단일 제품 크롤링 (URL 기반 크롤러 자동 선택)"""
        result = {
            "product_id": product["product_id"],
            "product_name": product["product_name"],
            "timestamp": datetime.now().isoformat(),
            "prices": [],
            "logs": [],
        }

        def get_crawler_for_url(url: str):
            """URL에 따라 새 크롤러 생성 (재사용 안함)"""
            from crawlers.ssg_crawler import SSGCrawler
            from crawlers.cj_crawler import CJCrawler
            from crawlers.shinsegae_crawler import ShinsegaeCrawler
            from crawlers.lotte_crawler import LotteCrawler
            from crawlers.gs_crawler import GSCrawler

            url_lower = url.lower()

            if "ssg.com" in url_lower and "shinsegaetvshopping.com" not in url_lower:
                return SSGCrawler()
            elif "cjonstyle.com" in url_lower:
                return CJCrawler()
            elif "shinsegaetvshopping.com" in url_lower:
                return ShinsegaeCrawler()
            elif "lotteimall.com" in url_lower:
                return LotteCrawler()
            elif "gsshop.com" in url_lower:
                return GSCrawler()
            else:
                return default_crawler

        # 제품명을 안전하게 잘라내기 (UTF-8 보장)
        product_name = str(product.get("product_name", "Unknown"))
        if len(product_name) > 20:
            product_name_short = product_name[:20] + "..."
        else:
            product_name_short = product_name

        # 제품별로 사용할 crawler 딕셔너리 (사이트별로 재사용)
        site_crawlers = {}

        try:
            # Waffle 크롤링
            if product.get("waffle") and product["waffle"].get("url"):
                url = product["waffle"]["url"]
                try:
                    site_key = "waffle"
                    if site_key not in site_crawlers:
                        site_crawlers[site_key] = get_crawler_for_url(url)

                    waffle_data = site_crawlers[site_key].crawl_price(url)
                    result["prices"].append({"seller": "waffle", **waffle_data})
                    price_info = f"{waffle_data.get('상품 가격', 'N/A')}원"
                    result["logs"].append(
                        ("INFO", f"✓ {product_name_short} Waffle: {price_info}")
                    )
                except Exception as e:
                    result["logs"].append(
                        ("ERROR", f"✗ {product_name_short} Waffle 실패: {str(e)[:50]}")
                    )
                    result["prices"].append({"seller": "waffle", "error": str(e)})

            # 경쟁사 크롤링
            for competitor in product.get("competitors", []):
                if competitor.get("url"):
                    url = competitor["url"]
                    seller_name = competitor["name"]
                    try:
                        # 같은 사이트면 crawler 재사용
                        url_lower = url.lower()
                        if "ssg.com" in url_lower:
                            site_key = "ssg"
                        elif "cjonstyle.com" in url_lower:
                            site_key = "cj"
                        elif "shinsegae.com" in url_lower:
                            site_key = "shinsegae"
                        elif "ellotte.com" in url_lower:
                            site_key = "lotte"
                        elif "gsshop.com" in url_lower:
                            site_key = "gs"
                        else:
                            site_key = seller_name

                        if site_key not in site_crawlers:
                            site_crawlers[site_key] = get_crawler_for_url(url)

                        comp_data = site_crawlers[site_key].crawl_price(url)
                        result["prices"].append({"seller": seller_name, **comp_data})
                        price_info = f"{comp_data.get('상품 가격', 'N/A')}원"
                        result["logs"].append(
                            (
                                "INFO",
                                f"✓ {product_name_short} {seller_name}: {price_info}",
                            )
                        )
                    except Exception as e:
                        result["logs"].append(
                            (
                                "ERROR",
                                f"✗ {product_name_short} {seller_name} 실패: {str(e)[:50]}",
                            )
                        )
                        result["prices"].append(
                            {"seller": seller_name, "error": str(e)}
                        )

        finally:
            # 제품 크롤링 완료 - 모든 crawler 정리
            for crawler in site_crawlers.values():
                try:
                    crawler._close_driver()
                except:
                    pass
        return result

    def _crawl_product_safe(
        self,
        product: Dict,
        default_crawler,
        job_id: int,
    ) -> Dict:
        """안전한 제품 크롤링 (병렬 처리용, 예외 처리 포함)"""
        try:
            return self._crawl_product(product, default_crawler, job_id, None)

            # 제품 크롤링 완료 후 즉시 Chrome 정리 (메모리 절약)
            try:
                if hasattr(thread_local, "ssg_crawler"):
                    thread_local.ssg_crawler._close_driver()
                if hasattr(thread_local, "cj_crawler"):
                    thread_local.cj_crawler._close_driver()
            except:
                pass

            return result
        except Exception as e:
            product_name = str(product.get("product_name", "Unknown"))
            if len(product_name) > 20:
                product_name_short = product_name[:20] + "..."
            else:
                product_name_short = product_name

            return {
                "product_id": product["product_id"],
                "product_name": product["product_name"],
                "timestamp": datetime.now().isoformat(),
                "prices": [],
                "error": str(e),
                "logs": [
                    ("ERROR", f"✗ {product_name_short} 치명적 오류: {str(e)[:50]}")
                ],
            }

    def _save_results(self, job_id: int, results: List[Dict], site_name: str) -> str:
        """결과를 Excel 파일로 저장 (xlsxwriter 사용 - 안정적)"""
        try:
            import xlsxwriter
            import os

            # 결과 폴더 생성
            results_dir = "results"
            os.makedirs(results_dir, exist_ok=True)

            # 파일명 생성 (한국 시간)
            kst_now = datetime.now(KST)
            timestamp = kst_now.strftime("%Y%m%d_%H%M%S")
            filename = f"{site_name}_가격조사_{timestamp}.xlsx"
            filepath = os.path.join(results_dir, filename)

            # 워크북 생성
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
            worksheet1 = workbook.add_worksheet("전체 결과")
            worksheet1.set_column("A:A", 20)
            worksheet1.set_column("B:B", 50)
            worksheet1.set_column("C:F", 15)

            row = 0
            for result in results:
                # 제품 정보
                worksheet1.write(
                    row, 0, f"제품명: {result['product_name']}", title_format
                )
                row += 1
                worksheet1.write(row, 0, f"제품ID: {result['product_id']}")
                row += 1
                worksheet1.write(row, 0, f"추출 시간: {result['timestamp']}")
                row += 2

                # 헤더
                headers = [
                    "판매처",
                    "상품 URL",
                    "상품가격",
                    "배송비",
                    "배송비여부",
                    "최종가격",
                ]
                for col, header in enumerate(headers):
                    worksheet1.write(row, col, header, header_format)
                row += 1

                # 데이터
                for price in result.get("prices", []):
                    seller = (
                        "Waffle (우리회사)"
                        if price["seller"] == "waffle"
                        else f"경쟁사 ({price['seller']})"
                    )
                    worksheet1.write_string(row, 0, seller)
                    worksheet1.write_string(row, 1, str(price.get("상품 url", "N/A")))

                    # 가격 데이터
                    p_val = price.get("상품 가격", "N/A")
                    if isinstance(p_val, (int, float)):
                        worksheet1.write_number(row, 2, p_val)
                    else:
                        worksheet1.write_string(row, 2, str(p_val))

                    s_val = price.get("배송비", "N/A")
                    if isinstance(s_val, (int, float)):
                        worksheet1.write_number(row, 3, s_val)
                    else:
                        worksheet1.write_string(row, 3, str(s_val))

                    worksheet1.write_string(
                        row, 4, str(price.get("배송비 여부", "N/A"))
                    )

                    f_val = price.get("최종 가격", "N/A")
                    if isinstance(f_val, (int, float)):
                        worksheet1.write_number(row, 5, f_val)
                    else:
                        worksheet1.write_string(row, 5, str(f_val))

                    row += 1
                row += 2  # 빈 줄

            # 시트2: 가격 역전 항목
            worksheet2 = workbook.add_worksheet("가격 역전 항목")
            worksheet2.set_column("A:A", 20)
            worksheet2.set_column("B:B", 50)
            worksheet2.set_column("C:F", 15)
            worksheet2.set_column("G:G", 20)

            row = 0
            # '='로 시작하지 않도록 변경 (Excel이 수식으로 오인하지 않도록)
            worksheet2.write_string(
                row, 0, "【가격 역전 항목 (경쟁사가 더 저렴한 경우)】", title_format
            )
            row += 2

            found_cheaper = False

            for result in results:
                # Waffle 가격 찾기
                waffle_price = None
                for price in result.get("prices", []):
                    if price["seller"] == "waffle":
                        waffle_price = price.get("최종 가격")
                        break

                if not isinstance(waffle_price, (int, float)):
                    continue

                # 더 저렴한 경쟁사 찾기
                cheaper_competitors = []
                for price in result.get("prices", []):
                    if price["seller"] != "waffle":
                        comp_price = price.get("최종 가격")
                        if (
                            isinstance(comp_price, (int, float))
                            and comp_price < waffle_price
                        ):
                            cheaper_competitors.append(price)

                if cheaper_competitors:
                    found_cheaper = True

                    # 제품 정보
                    worksheet2.write(
                        row, 0, f"제품명: {result['product_name']}", bold_format
                    )
                    row += 1
                    worksheet2.write(row, 0, f"제품ID: {result['product_id']}")
                    row += 2

                    # 헤더
                    headers = [
                        "판매처",
                        "상품 URL",
                        "상품가격",
                        "배송비",
                        "배송비여부",
                        "최종가격",
                        "가격차이",
                    ]
                    for col, header in enumerate(headers):
                        worksheet2.write(row, col, header, header_format)
                    row += 1

                    # Waffle 가격
                    for price in result.get("prices", []):
                        if price["seller"] == "waffle":
                            worksheet2.write_string(row, 0, "Waffle (우리회사)")
                            worksheet2.write_string(
                                row, 1, str(price.get("상품 url", "N/A"))
                            )

                            wp_val = price.get("상품 가격", "N/A")
                            if isinstance(wp_val, (int, float)):
                                worksheet2.write_number(row, 2, wp_val)
                            else:
                                worksheet2.write_string(row, 2, str(wp_val))

                            ws_val = price.get("배송비", "N/A")
                            if isinstance(ws_val, (int, float)):
                                worksheet2.write_number(row, 3, ws_val)
                            else:
                                worksheet2.write_string(row, 3, str(ws_val))

                            worksheet2.write_string(
                                row, 4, str(price.get("배송비 여부", "N/A"))
                            )
                            worksheet2.write_number(row, 5, waffle_price)
                            worksheet2.write_string(row, 6, "-")
                            row += 1
                            break

                    # 더 저렴한 경쟁사
                    for comp in cheaper_competitors:
                        comp_price = comp.get("최종 가격")
                        price_diff = int(waffle_price - comp_price)

                        worksheet2.write_string(row, 0, f"경쟁사 ({comp['seller']})")
                        worksheet2.write_string(
                            row, 1, str(comp.get("상품 url", "N/A"))
                        )

                        cp_val = comp.get("상품 가격", "N/A")
                        if isinstance(cp_val, (int, float)):
                            worksheet2.write_number(row, 2, cp_val)
                        else:
                            worksheet2.write_string(row, 2, str(cp_val))

                        cs_val = comp.get("배송비", "N/A")
                        if isinstance(cs_val, (int, float)):
                            worksheet2.write_number(row, 3, cs_val)
                        else:
                            worksheet2.write_string(row, 3, str(cs_val))

                        worksheet2.write_string(
                            row, 4, str(comp.get("배송비 여부", "N/A"))
                        )
                        worksheet2.write_number(row, 5, comp_price)
                        worksheet2.write(
                            row, 6, f"-{price_diff}원 저렴", bold_red_format
                        )
                        row += 1

                    row += 2  # 빈 줄

            if not found_cheaper:
                worksheet2.write(row, 0, "가격 역전 항목이 없습니다.")

            # 파일 닫기 (중요!)
            workbook.close()
            return filepath

        except Exception as e:
            print(f"Excel 저장 실패: {str(e)}")
            import traceback

            traceback.print_exc()
            return None

    def _add_log(self, job_id: int, level: str, message: str):
        """로그 추가 (UTF-8 인코딩 보장)"""
        try:
            # 메시지가 문자열인지 확인하고 UTF-8로 인코딩/디코딩 확인
            if isinstance(message, bytes):
                message = message.decode("utf-8", errors="replace")
            else:
                # 문자열을 UTF-8로 인코딩했다가 다시 디코딩하여 유효성 확인
                message = message.encode("utf-8", errors="replace").decode("utf-8")

            log = CrawlingLog(job_id=job_id, level=level, message=message)
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            print(f"로그 추가 실패: {str(e)}")
            db.session.rollback()


# 전역 엔진 인스턴스
crawling_engine = CrawlingEngine()
