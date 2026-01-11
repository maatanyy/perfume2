from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import db
from utils.decorators import approved_required
from utils.google_sheets import get_sheet_list, extract_spreadsheet_id
from utils.crawling_engine import crawling_engine
from datetime import datetime

dashboard_bp = Blueprint("dashboard", __name__)

# 시스템 제한 설정
MAX_CONCURRENT_JOBS_PER_USER = 3  # 사용자당 최대 작업 수 (메모리 최적화)
MAX_TOTAL_CONCURRENT_JOBS = 5  # 전체 시스템 최대 작업 수 (4GB RAM 안정 운영)


@dashboard_bp.route("/")
@login_required
@approved_required
def index():
    """대시보드 메인"""
    from models.crawling_job import CrawlingJob

    # 사용자의 크롤링 작업 목록
    active_jobs = (
        CrawlingJob.query.filter_by(user_id=current_user.id, status="running")
        .order_by(CrawlingJob.created_at.desc())
        .all()
    )

    completed_jobs = (
        CrawlingJob.query.filter_by(user_id=current_user.id, status="completed")
        .order_by(CrawlingJob.completed_at.desc())
        .limit(10)
        .all()
    )

    failed_jobs = (
        CrawlingJob.query.filter_by(user_id=current_user.id, status="failed")
        .order_by(CrawlingJob.completed_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "dashboard/index.html",
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
    )


@dashboard_bp.route("/start", methods=["GET", "POST"])
@login_required
@approved_required
def start_crawling():
    """크롤링 시작"""
    from models.crawling_job import CrawlingJob

    # 고정된 구글 시트 URL
    FIXED_SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1LfV2DZSZ262uWLi872OIxuL9QemrmktiOjnz2DU0l0s/edit?gid=107629138#gid=107629138"

    if request.method == "POST":
        sheet_name = request.form.get("sheet_name", "").strip()

        if not sheet_name:
            flash("시트를 선택해주세요.", "error")
            return redirect(url_for("dashboard.start_crawling"))

        # 시트 이름 = 사이트 이름
        site_name = sheet_name

        # 사용자의 동시 작업 수 확인
        active_count = CrawlingJob.query.filter_by(
            user_id=current_user.id, status="running"
        ).count()

        if active_count >= MAX_CONCURRENT_JOBS_PER_USER:
            flash(
                f"동시에 실행할 수 있는 작업 수를 초과했습니다. (최대 {MAX_CONCURRENT_JOBS_PER_USER}개)",
                "error",
            )
            return redirect(url_for("dashboard.index"))

        # 전체 시스템 동시 작업 수 확인
        total_active_count = CrawlingJob.query.filter_by(status="running").count()

        if total_active_count >= MAX_TOTAL_CONCURRENT_JOBS:
            flash(
                f"시스템이 현재 바쁩니다. 잠시 후 다시 시도해주세요. (현재 {total_active_count}개 작업 실행 중)",
                "warning",
            )
            return redirect(url_for("dashboard.index"))

        # 작업 생성
        job = CrawlingJob(
            user_id=current_user.id,
            site_name=site_name,
            status="pending",
            google_sheet_url=FIXED_SPREADSHEET_URL,
            sheet_name=sheet_name,
        )
        db.session.add(job)
        db.session.commit()

        # 크롤링 시작
        crawling_engine.start_crawling(job, FIXED_SPREADSHEET_URL, sheet_name)

        flash("크롤링이 시작되었습니다.", "success")
        return redirect(url_for("dashboard.index"))

    # GET 요청: 시트 목록 불러오기
    spreadsheet_url = FIXED_SPREADSHEET_URL
    sheets = []

    try:
        spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
        if spreadsheet_id:
            sheets = get_sheet_list(spreadsheet_id)
    except Exception as e:
        flash(f"시트 목록을 불러오는 중 오류가 발생했습니다: {str(e)}", "error")

    return render_template(
        "dashboard/start_crawling.html",
        spreadsheet_url=spreadsheet_url,
        sheets=sheets,
        fixed_sheet=True,
    )


@dashboard_bp.route("/job/<int:job_id>")
@login_required
@approved_required
def job_detail(job_id):
    """작업 상세 정보"""
    from models.crawling_job import CrawlingJob
    from models.crawling_log import CrawlingLog

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        flash("권한이 없습니다.", "error")
        return redirect(url_for("dashboard.index"))

    logs = (
        CrawlingLog.query.filter_by(job_id=job_id)
        .order_by(CrawlingLog.created_at.desc())
        .limit(100)
        .all()
    )

    return render_template("dashboard/job_detail.html", job=job, logs=logs)


@dashboard_bp.route("/job/<int:job_id>/status")
@login_required
@approved_required
def job_status(job_id):
    """작업 상태 조회 (AJAX용)"""
    from models.crawling_job import CrawlingJob
    from models.crawling_log import CrawlingLog

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        return jsonify({"error": "권한이 없습니다."}), 403

    # 최근 로그 10개
    recent_logs = (
        CrawlingLog.query.filter_by(job_id=job_id)
        .order_by(CrawlingLog.created_at.desc())
        .limit(10)
        .all()
    )

    return jsonify(
        {
            "status": job.status,
            "progress": job.progress,
            "processed_items": job.processed_items,
            "total_items": job.total_items,
            "error_message": job.error_message,
            "logs": [
                {
                    "level": log.level,
                    "message": log.message,
                    "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
                for log in recent_logs
            ],
        }
    )


@dashboard_bp.route("/job/<int:job_id>/cancel", methods=["POST"])
@login_required
@approved_required
def cancel_job(job_id):
    """작업 취소"""
    from models.crawling_job import CrawlingJob

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        flash("권한이 없습니다.", "error")
        return redirect(url_for("dashboard.index"))

    if job.status not in ["pending", "running"]:
        flash("취소할 수 없는 작업입니다.", "error")
        return redirect(url_for("dashboard.job_detail", job_id=job_id))

    crawling_engine.cancel_job(job_id)
    flash("작업 취소 요청이 전송되었습니다.", "info")

    return redirect(url_for("dashboard.job_detail", job_id=job_id))


@dashboard_bp.route("/job/<int:job_id>/delete", methods=["POST"])
@login_required
@approved_required
def delete_job(job_id):
    """작업 삭제"""
    from models.crawling_job import CrawlingJob
    import time

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        flash("권한이 없습니다.", "error")
        return redirect(url_for("dashboard.index"))

    # 실행 중이거나 대기 중인 작업은 자동으로 취소
    if job.status in ["running", "pending"]:
        crawling_engine.cancel_job(job_id)
        job.cancel()  # 상태를 cancelled로 변경
        db.session.commit()
        # 취소가 완료될 때까지 잠시 대기
        time.sleep(0.5)

    # 작업 삭제 (cascade로 로그도 함께 삭제됨)
    db.session.delete(job)
    db.session.commit()

    flash("작업이 삭제되었습니다.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/job/<int:job_id>/download")
@login_required
@approved_required
def download_result(job_id):
    """결과 파일 다운로드"""
    from models.crawling_job import CrawlingJob
    from flask import send_file
    import os

    job = CrawlingJob.query.get_or_404(job_id)

    # 권한 확인
    if job.user_id != current_user.id and not current_user.is_admin:
        flash("권한이 없습니다.", "error")
        return redirect(url_for("dashboard.index"))

    # 파일 확인
    if not job.result_file or not os.path.exists(job.result_file):
        flash("결과 파일을 찾을 수 없습니다.", "error")
        return redirect(url_for("dashboard.job_detail", job_id=job_id))

    # 파일 다운로드
    return send_file(
        job.result_file,
        as_attachment=True,
        download_name=os.path.basename(job.result_file),
    )


@dashboard_bp.route("/history")
@login_required
@approved_required
def history():
    """작업 히스토리"""
    from models.crawling_job import CrawlingJob

    page = request.args.get("page", 1, type=int)
    per_page = 20

    jobs = (
        CrawlingJob.query.filter_by(user_id=current_user.id)
        .order_by(CrawlingJob.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return render_template("dashboard/history.html", jobs=jobs)
