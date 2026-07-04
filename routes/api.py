"""API 엔드포인트 - SSE 실시간 진행률 스트림 포함"""

import json
import queue
from flask import Blueprint, jsonify, request, Response, stream_with_context
from flask_login import login_required, current_user
from database import db
from utils.decorators import approved_required
from utils.google_sheets import get_sheet_list, extract_spreadsheet_id
from app import limiter
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


# =========================================================
# 진행률 - SSE 스트림 (실시간)
# =========================================================

@api_bp.route("/jobs/<int:job_id>/stream")
@login_required
@approved_required
@limiter.exempt
def stream_progress(job_id):
    """
    SSE 스트리밍 엔드포인트.
    크롤링 아이템 완료마다 진행률/ETA 실시간 push.
    """
    from models.crawling_job import CrawlingJob
    from utils.crawling_engine_v2 import get_crawling_engine_v2

    job = CrawlingJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        return Response("data: {\"error\": \"권한 없음\"}\n\n", mimetype="text/event-stream")

    engine = get_crawling_engine_v2()
    q = engine.create_sse_queue(job_id)

    def generate():
        try:
            # 현재 상태 즉시 전송 (연결 직후 UI 초기화용)
            initial = {
                "processed": job.processed_items or 0,
                "total": job.total_items or 0,
                "percent": job.progress or 0,
                "eta_display": "계산 중...",
                "speed": 0,
                "last_item": "",
                "success": 0,
                "sold_out": 0,
                "not_found": 0,
                "error": 0,
                "status": job.status,
            }
            yield f"data: {json.dumps(initial, ensure_ascii=False)}\n\n"

            while True:
                try:
                    data = q.get(timeout=25)
                    if data is None:
                        # 크롤링 완료 - 최종 상태 전송
                        try:
                            from models.crawling_job import CrawlingJob as CJ
                            fresh_job = db.session.get(CJ, job_id)
                            db.session.expire_all()
                        except Exception:
                            fresh_job = job
                        final = {
                            "processed": (fresh_job.processed_items or 0) if fresh_job else 0,
                            "total": (fresh_job.total_items or 0) if fresh_job else 0,
                            "percent": 100,
                            "eta_display": "완료",
                            "speed": 0,
                            "last_item": "크롤링 완료",
                            "status": fresh_job.status if fresh_job else "completed",
                            "done": True,
                        }
                        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                        break
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

                except queue.Empty:
                    # 30초마다 heartbeat (연결 유지) - 새 세션으로 조회해 DB 락 방지
                    try:
                        from models.crawling_job import CrawlingJob as CJ
                        fresh_job = db.session.get(CJ, job_id)
                        current_status = fresh_job.status if fresh_job else "unknown"
                        db.session.expire_all()
                    except Exception:
                        current_status = "unknown"
                    if current_status not in ["pending", "running"]:
                        yield f"data: {json.dumps({'done': True, 'status': current_status}, ensure_ascii=False)}\n\n"
                        break
                    yield f"data: {json.dumps({'heartbeat': True}, ensure_ascii=False)}\n\n"

        except GeneratorExit:
            pass
        finally:
            engine.remove_sse_queue(job_id)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 비활성화
        },
    )


# =========================================================
# 진행률 - 폴링 방식 (SSE 미지원 환경 fallback)
# =========================================================

@api_bp.route("/progress/<int:job_id>")
@login_required
@approved_required
@limiter.exempt
def get_progress(job_id):
    """작업 진행률 조회 (폴링 fallback)"""
    from models.crawling_job import CrawlingJob
    from utils.crawling_engine_v2 import get_crawling_engine_v2

    job = CrawlingJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "권한이 없습니다."}), 403

    engine = get_crawling_engine_v2()
    stats = engine.get_job_stats(job_id)

    return jsonify({
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "current": job.processed_items,
        "total": job.total_items,
        "error": job.error_message,
        "stats": stats or {},
    })


# =========================================================
# 시트 목록
# =========================================================

@api_bp.route("/sheets", methods=["POST"])
@login_required
@approved_required
def get_sheets():
    """구글 시트 목록 가져오기"""
    data = request.get_json()
    spreadsheet_url = data.get("spreadsheet_url", "").strip()

    if not spreadsheet_url:
        return jsonify({"error": "시트 URL이 필요합니다."}), 400

    try:
        spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
        if not spreadsheet_id:
            return jsonify({"error": "올바른 시트 URL이 아닙니다."}), 400
        sheets = get_sheet_list(spreadsheet_id)
        return jsonify({"sheets": sheets})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =========================================================
# 작업 목록 / 통계
# =========================================================

@api_bp.route("/jobs")
@login_required
@approved_required
def get_jobs():
    from models.crawling_job import CrawlingJob
    status = request.args.get("status")
    query = CrawlingJob.query.filter_by(user_id=current_user.id)
    if status:
        query = query.filter_by(status=status)
    jobs = query.order_by(CrawlingJob.created_at.desc()).limit(20).all()
    return jsonify({
        "jobs": [
            {
                "id": job.id,
                "site_name": job.site_name,
                "status": job.status,
                "progress": job.progress,
                "created_at": job.created_at.isoformat(),
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            }
            for job in jobs
        ]
    })


@api_bp.route("/jobs/<int:job_id>/stats")
@login_required
@approved_required
def get_job_stats(job_id):
    from models.crawling_job import CrawlingJob
    from utils.crawling_engine_v2 import get_crawling_engine_v2

    job = CrawlingJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "권한이 없습니다."}), 403

    try:
        stats = get_crawling_engine_v2().get_job_stats(job_id)
        return jsonify({
            "job": {
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "site_name": job.site_name,
                "total_items": job.total_items,
                "processed_items": job.processed_items,
                "error_message": job.error_message,
            },
            "stats": stats or {},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:job_id>/logs")
@login_required
@approved_required
def get_job_logs(job_id):
    from models.crawling_job import CrawlingJob
    from models.crawling_log import CrawlingLog

    job = CrawlingJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "권한이 없습니다."}), 403

    limit = request.args.get("limit", 100, type=int)
    logs = (
        CrawlingLog.query.filter_by(job_id=job_id)
        .order_by(CrawlingLog.id.desc())
        .limit(limit)
        .all()
    )
    return jsonify({
        "logs": [
            {
                "id": log.id,
                "level": log.level,
                "message": log.message,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in reversed(logs)
        ]
    })


# =========================================================
# 시스템 모니터링 (관리자용)
# =========================================================

@api_bp.route("/system/status")
@login_required
@approved_required
def get_system_status():
    try:
        from utils.crawling_engine_v2 import crawling_engine_v2
        status = crawling_engine_v2.get_system_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/memory")
@login_required
@approved_required
def get_memory_status():
    try:
        from utils.memory_monitor import get_memory_monitor
        monitor = get_memory_monitor()
        return jsonify({
            "current": monitor.get_current_usage(),
            "stats": monitor.get_stats(),
            "history": monitor.get_history(minutes=5),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/memory/gc", methods=["POST"])
@login_required
@approved_required
def force_garbage_collection():
    if not current_user.is_admin:
        return jsonify({"error": "관리자 권한이 필요합니다."}), 403
    try:
        import gc
        from utils.memory_monitor import get_memory_monitor
        monitor = get_memory_monitor()
        before = monitor.get_current_usage()
        gc.collect()
        gc.collect()
        after = monitor.get_current_usage()
        return jsonify({
            "success": True,
            "before_mb": before.get("rss_mb", 0),
            "after_mb": after.get("rss_mb", 0),
            "freed_mb": round(before.get("rss_mb", 0) - after.get("rss_mb", 0), 1),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/browser-pool")
@login_required
@approved_required
def get_browser_pool_status():
    try:
        from utils.browser_pool import get_browser_pool
        pool = get_browser_pool()
        return jsonify(pool.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/browser-pool/reset", methods=["POST"])
@login_required
@approved_required
def reset_browser_pool():
    if not current_user.is_admin:
        return jsonify({"error": "관리자 권한이 필요합니다."}), 403
    try:
        import gc
        from utils.browser_pool import shutdown_browser_pool
        shutdown_browser_pool()
        gc.collect()
        return jsonify({"success": True, "message": "브라우저 풀이 리셋되었습니다."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
