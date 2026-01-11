"""관리자 라우트"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from database import db
from utils.decorators import admin_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/")
@login_required
@admin_required
def index():
    """관리자 대시보드"""
    from models.user import User
    from models.crawling_job import CrawlingJob

    pending_users = (
        User.query.filter_by(is_approved=False).order_by(User.created_at.desc()).all()
    )
    all_users = User.query.order_by(User.created_at.desc()).all()
    active_jobs = (
        CrawlingJob.query.filter_by(status="running")
        .order_by(CrawlingJob.started_at.desc())
        .all()
    )

    return render_template(
        "admin/index.html",
        pending_users=pending_users,
        all_users=all_users,
        active_jobs=active_jobs,
    )


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    """사용자 관리"""
    from models.user import User

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


@admin_bp.route("/user/<int:user_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_user(user_id):
    """사용자 승인"""
    from models.user import User

    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    flash(f"{user.email} 사용자를 승인했습니다.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/user/<int:user_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_user(user_id):
    """사용자 거부 (삭제)"""
    from models.user import User

    user = User.query.get_or_404(user_id)
    email = user.email
    db.session.delete(user)
    db.session.commit()
    flash(f"{email} 사용자를 삭제했습니다.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/user/<int:user_id>/toggle_admin", methods=["POST"])
@login_required
@admin_required
def toggle_admin(user_id):
    """관리자 권한 토글"""
    from models.user import User

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("자신의 권한은 변경할 수 없습니다.", "error")
        return redirect(url_for("admin.users"))

    user.is_admin = not user.is_admin
    db.session.commit()
    status = "관리자로" if user.is_admin else "일반 사용자로"
    flash(f"{user.email}을(를) {status} 변경했습니다.", "success")
    return redirect(url_for("admin.users"))
