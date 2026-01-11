"""API 엔드포인트"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from database import db
from utils.decorators import approved_required
from utils.google_sheets import get_sheet_list, extract_spreadsheet_id

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
