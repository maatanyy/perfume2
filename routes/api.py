"""API 엔드포인트"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from database import db
from utils.decorators import approved_required
from utils.google_sheets import get_sheet_list, extract_spreadsheet_id
import logging

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)


@api_bp.route("/progress/<int:job_id>")
@login_required
@approved_required
def get_progress(job_id):
    """작업 진행률 조회"""
    from models.crawling_job import CrawlingJob

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "권한이 없습니다."}), 403

    return jsonify(
        {
            "id": job.id,
            "status": job.status,
            "progress": job.progress,
            "current": job.processed_items,
            "total": job.total_items,
            "error": job.error_message,
        }
    )


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


@api_bp.route("/jobs")
@login_required
@approved_required
def get_jobs():
    """작업 목록 조회"""
    from models.crawling_job import CrawlingJob

    status = request.args.get("status")
    query = CrawlingJob.query.filter_by(user_id=current_user.id)

    if status:
        query = query.filter_by(status=status)

    jobs = query.order_by(CrawlingJob.created_at.desc()).limit(20).all()

    return jsonify(
        {
            "jobs": [
                {
                    "id": job.id,
                    "site_name": job.site_name,
                    "status": job.status,
                    "progress": job.progress,
                    "created_at": job.created_at.isoformat(),
                    "completed_at": (
                        job.completed_at.isoformat() if job.completed_at else None
                    ),
                }
                for job in jobs
            ]
        }
    )


# ============================================
# 시스템 모니터링 API (관리자용)
# ============================================


@api_bp.route("/system/status")
@login_required
@approved_required
def get_system_status():
    """시스템 상태 조회 (메모리, 브라우저 풀, 활성 작업)"""
    try:
        from utils.crawling_engine_v2 import crawling_engine_v2

        status = crawling_engine_v2.get_system_status()
        return jsonify(status)
    except Exception as e:
        logger.error(f"시스템 상태 조회 실패: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/memory")
@login_required
@approved_required
def get_memory_status():
    """메모리 상태 조회"""
    try:
        from utils.memory_monitor import get_memory_monitor

        monitor = get_memory_monitor()
        return jsonify(
            {
                "current": monitor.get_current_usage(),
                "stats": monitor.get_stats(),
                "history": monitor.get_history(minutes=5),
            }
        )
    except Exception as e:
        logger.error(f"메모리 상태 조회 실패: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/memory/gc", methods=["POST"])
@login_required
@approved_required
def force_garbage_collection():
    """강제 가비지 컬렉션"""
    if not current_user.is_admin:
        return jsonify({"error": "관리자 권한이 필요합니다."}), 403

    try:
        from utils.memory_monitor import get_memory_monitor
        import gc

        monitor = get_memory_monitor()
        before = monitor.get_current_usage()

        gc.collect()
        gc.collect()

        after = monitor.get_current_usage()

        return jsonify(
            {
                "success": True,
                "before_mb": before.get("rss_mb", 0),
                "after_mb": after.get("rss_mb", 0),
                "freed_mb": round(before.get("rss_mb", 0) - after.get("rss_mb", 0), 1),
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/browser-pool")
@login_required
@approved_required
def get_browser_pool_status():
    """브라우저 풀 상태 조회"""
    try:
        from utils.browser_pool import get_browser_pool

        pool = get_browser_pool()
        return jsonify(pool.get_stats())
    except Exception as e:
        logger.error(f"브라우저 풀 상태 조회 실패: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/system/browser-pool/reset", methods=["POST"])
@login_required
@approved_required
def reset_browser_pool():
    """브라우저 풀 리셋 (관리자 전용)"""
    if not current_user.is_admin:
        return jsonify({"error": "관리자 권한이 필요합니다."}), 403

    try:
        from utils.browser_pool import shutdown_browser_pool, get_browser_pool
        import gc

        # 기존 풀 종료
        shutdown_browser_pool()
        gc.collect()

        # 새 풀 생성 (lazy)
        # get_browser_pool()  # 필요할 때 자동 생성됨

        return jsonify({"success": True, "message": "브라우저 풀이 리셋되었습니다."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:job_id>/stats")
@login_required
@approved_required
def get_job_stats(job_id):
    """작업 상세 통계 조회"""
    from models.crawling_job import CrawlingJob

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "권한이 없습니다."}), 403

    try:
        from utils.crawling_engine_v2 import crawling_engine_v2

        stats = crawling_engine_v2.get_job_stats(job_id)

        return jsonify(
            {
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
            }
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/jobs/<int:job_id>/logs")
@login_required
@approved_required
def get_job_logs(job_id):
    """작업 로그 조회"""
    from models.crawling_job import CrawlingJob
    from models.crawling_log import CrawlingLog

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "권한이 없습니다."}), 403

    # 최근 로그 100개
    limit = request.args.get("limit", 100, type=int)
    logs = (
        CrawlingLog.query.filter_by(job_id=job_id)
        .order_by(CrawlingLog.id.desc())
        .limit(limit)
        .all()
    )

    return jsonify(
        {
            "logs": [
                {
                    "id": log.id,
                    "level": log.level,
                    "message": log.message,
                    "created_at": (
                        log.created_at.isoformat() if log.created_at else None
                    ),
                }
                for log in reversed(logs)  # 시간순 정렬
            ]
        }
    )
