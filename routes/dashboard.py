from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from database import db
from utils.decorators import approved_required
from utils.google_sheets import get_sheet_list, extract_spreadsheet_id
from app import limiter
from utils.crawling_engine_v2 import get_crawling_engine_v2
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)

MAX_CONCURRENT_JOBS_PER_USER = 5
MAX_TOTAL_CONCURRENT_JOBS = 10

# 사이트별 메타 정보
SITE_CONFIG = {
    "ssg": {"label": "SSG.COM", "domain": "ssg.com", "icon": "🛒"},
    "cj": {"label": "CJ온스타일", "domain": "cjonstyle.com", "icon": "📺"},
    "ssg_shoping": {"label": "신세계TV쇼핑", "domain": "shinsegaetvshopping.com", "icon": "🏪"},
    "롯데아이몰": {"label": "롯데아이몰", "domain": "lotteimall.com", "icon": "🎡"},
    "gs": {"label": "GS샵", "domain": "gsshop.com", "icon": "🏬"},
}


def get_crawling_engine():
    return get_crawling_engine_v2()


@dashboard_bp.route("/")
@login_required
@approved_required
def index():
    """대시보드 메인 - 사이트별 카드 UI"""
    from models.crawling_job import CrawlingJob

    # 사이트별 최신 작업 상태 조회
    site_jobs = {}
    for site_key in SITE_CONFIG.keys():
        latest = (
            CrawlingJob.query
            .filter_by(user_id=current_user.id, site_name=site_key)
            .order_by(CrawlingJob.created_at.desc())
            .first()
        )
        site_jobs[site_key] = latest

    # 전체 활성 작업
    active_jobs = (
        CrawlingJob.query
        .filter_by(user_id=current_user.id)
        .filter(CrawlingJob.status.in_(["pending", "running"]))
        .order_by(CrawlingJob.created_at.desc())
        .all()
    )

    # 최근 완료 작업
    recent_jobs = (
        CrawlingJob.query
        .filter_by(user_id=current_user.id)
        .filter(CrawlingJob.status.in_(["completed", "failed", "cancelled"]))
        .order_by(CrawlingJob.completed_at.desc())
        .limit(10)
        .all()
    )

    return render_template(
        "dashboard/index.html",
        site_config=SITE_CONFIG,
        site_jobs=site_jobs,
        active_jobs=active_jobs,
        recent_jobs=recent_jobs,
    )


@dashboard_bp.route("/settings", methods=["GET", "POST"])
@login_required
@approved_required
def settings():
    """구글 시트 URL 설정"""
    from flask import session

    if request.method == "POST":
        sheet_url = request.form.get("sheet_url", "").strip()
        if not sheet_url:
            flash("구글 시트 URL을 입력해주세요.", "error")
        else:
            session["sheet_url"] = sheet_url
            flash("구글 시트 URL이 저장되었습니다.", "success")
        return redirect(url_for("dashboard.settings"))

    current_url = request.args.get("url") or ""
    return render_template("dashboard/settings.html", current_url=current_url)


@dashboard_bp.route("/start/<site_name>", methods=["POST"])
@login_required
@approved_required
def start_site(site_name):
    """특정 사이트 크롤링 시작"""
    from models.crawling_job import CrawlingJob
    from flask import session

    if site_name not in SITE_CONFIG:
        flash("지원하지 않는 사이트입니다.", "error")
        return redirect(url_for("dashboard.index"))

    sheet_url = request.form.get("sheet_url", "").strip()
    if not sheet_url:
        flash("구글 시트 URL을 입력해주세요.", "error")
        return redirect(url_for("dashboard.index"))

    spreadsheet_id = extract_spreadsheet_id(sheet_url)
    if not spreadsheet_id:
        flash("올바른 구글 시트 URL을 입력해주세요. (예: https://docs.google.com/spreadsheets/d/...)", "error")
        return redirect(url_for("dashboard.index"))

    # 중복 실행 확인 (같은 사이트가 이미 실행 중이면 차단)
    running = CrawlingJob.query.filter_by(
        user_id=current_user.id,
        site_name=site_name,
        status="running",
    ).first()
    if running:
        flash(f"{SITE_CONFIG[site_name]['label']}이(가) 이미 실행 중입니다.", "warning")
        return redirect(url_for("dashboard.index"))

    # 동시 작업 수 확인
    active_count = CrawlingJob.query.filter_by(
        user_id=current_user.id, status="running"
    ).count()
    if active_count >= MAX_CONCURRENT_JOBS_PER_USER:
        flash(f"동시 실행 가능한 작업 수를 초과했습니다. (최대 {MAX_CONCURRENT_JOBS_PER_USER}개)", "error")
        return redirect(url_for("dashboard.index"))

    total_active = CrawlingJob.query.filter_by(status="running").count()
    if total_active >= MAX_TOTAL_CONCURRENT_JOBS:
        flash(f"시스템이 현재 바쁩니다. 잠시 후 다시 시도해주세요.", "warning")
        return redirect(url_for("dashboard.index"))

    job = CrawlingJob(
        user_id=current_user.id,
        site_name=site_name,
        status="pending",
        google_sheet_url=sheet_url,
        sheet_name=site_name,
    )
    db.session.add(job)
    db.session.commit()

    get_crawling_engine().start_crawling(job, sheet_url, site_name)

    flash(f"{SITE_CONFIG[site_name]['label']} 크롤링이 시작되었습니다.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/start_all", methods=["POST"])
@login_required
@approved_required
def start_all():
    """전체 사이트 동시 크롤링 시작"""
    from models.crawling_job import CrawlingJob

    sheet_url = request.form.get("sheet_url", "").strip()
    if not sheet_url:
        flash("구글 시트 URL을 입력해주세요.", "error")
        return redirect(url_for("dashboard.index"))

    spreadsheet_id = extract_spreadsheet_id(sheet_url)
    if not spreadsheet_id:
        flash("올바른 구글 시트 URL을 입력해주세요. (예: https://docs.google.com/spreadsheets/d/...)", "error")
        return redirect(url_for("dashboard.index"))

    started = []
    skipped = []

    for site_name, site_info in SITE_CONFIG.items():
        # 이미 실행 중인 사이트는 건너뜀
        running = CrawlingJob.query.filter_by(
            user_id=current_user.id,
            site_name=site_name,
            status="running",
        ).first()
        if running:
            skipped.append(site_info["label"])
            continue

        total_active = CrawlingJob.query.filter_by(status="running").count()
        if total_active >= MAX_TOTAL_CONCURRENT_JOBS:
            skipped.append(site_info["label"])
            continue

        job = CrawlingJob(
            user_id=current_user.id,
            site_name=site_name,
            status="pending",
            google_sheet_url=sheet_url,
            sheet_name=site_name,
        )
        db.session.add(job)
        db.session.commit()

        get_crawling_engine().start_crawling(job, sheet_url, site_name)
        started.append(site_info["label"])

    if started:
        flash(f"크롤링 시작: {', '.join(started)}", "success")
    if skipped:
        flash(f"건너뜀 (이미 실행 중 또는 시스템 한도): {', '.join(skipped)}", "warning")

    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/job/<int:job_id>")
@login_required
@approved_required
def job_detail(job_id):
    """작업 상세 정보"""
    from models.crawling_job import CrawlingJob
    from models.crawling_log import CrawlingLog

    job = CrawlingJob.query.get_or_404(job_id)

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


@dashboard_bp.route("/job/<int:job_id>/cancel", methods=["POST"])
@login_required
@approved_required
def cancel_job(job_id):
    from models.crawling_job import CrawlingJob

    job = CrawlingJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        flash("권한이 없습니다.", "error")
        return redirect(url_for("dashboard.index"))

    if job.status not in ["pending", "running"]:
        flash("취소할 수 없는 작업입니다.", "error")
        return redirect(url_for("dashboard.job_detail", job_id=job_id))

    get_crawling_engine().cancel_job(job_id)
    flash("작업 취소 요청이 전송되었습니다.", "info")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/job/<int:job_id>/delete", methods=["POST"])
@login_required
@approved_required
def delete_job(job_id):
    from models.crawling_job import CrawlingJob
    import time

    job = CrawlingJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        flash("권한이 없습니다.", "error")
        return redirect(url_for("dashboard.index"))

    if job.status in ["running", "pending"]:
        get_crawling_engine().cancel_job(job_id)
        job.cancel()
        db.session.commit()
        time.sleep(0.5)

    db.session.delete(job)
    db.session.commit()

    flash("작업이 삭제되었습니다.", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/job/<int:job_id>/download")
@login_required
@approved_required
def download_result(job_id):
    from models.crawling_job import CrawlingJob
    from flask import send_file
    import os

    job = CrawlingJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        flash("권한이 없습니다.", "error")
        return redirect(url_for("dashboard.index"))

    if not job.result_file or not os.path.exists(job.result_file):
        flash("결과 파일을 찾을 수 없습니다.", "error")
        return redirect(url_for("dashboard.job_detail", job_id=job_id))

    return send_file(
        job.result_file,
        as_attachment=True,
        download_name=os.path.basename(job.result_file),
    )


@dashboard_bp.route("/history")
@login_required
@approved_required
def history():
    from models.crawling_job import CrawlingJob

    page = request.args.get("page", 1, type=int)
    per_page = 20
    jobs = (
        CrawlingJob.query.filter_by(user_id=current_user.id)
        .order_by(CrawlingJob.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    return render_template("dashboard/history.html", jobs=jobs)
