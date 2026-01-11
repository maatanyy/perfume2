from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from database import db
from utils.decorators import admin_required
import re

auth_bp = Blueprint("auth", __name__)


def validate_email(email):
    """이메일 형식 검증"""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(pattern, email) is not None


def validate_password(password):
    """비밀번호 강도 검증 (최소 8자, 영문+숫자 조합 권장)"""
    if len(password) < 8:
        return False, "비밀번호는 최소 8자 이상이어야 합니다."
    if not re.search(r"[a-zA-Z]", password):
        return False, "비밀번호에 영문자가 포함되어야 합니다."
    if not re.search(r"\d", password):
        return False, "비밀번호에 숫자가 포함되어야 합니다."
    return True, ""


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """회원가입"""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        from models.user import User

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        # 유효성 검사
        if not email:
            flash("이메일을 입력해주세요.", "error")
            return render_template("auth/register.html")

        if not validate_email(email):
            flash("올바른 이메일 형식이 아닙니다.", "error")
            return render_template("auth/register.html")

        if not password:
            flash("비밀번호를 입력해주세요.", "error")
            return render_template("auth/register.html")

        if password != password_confirm:
            flash("비밀번호가 일치하지 않습니다.", "error")
            return render_template("auth/register.html")

        is_valid, error_msg = validate_password(password)
        if not is_valid:
            flash(error_msg, "warning")
            # 경고이지만 계속 진행 가능

        # 중복 확인
        if User.query.filter_by(email=email).first():
            flash("이미 등록된 이메일입니다.", "error")
            return render_template("auth/register.html")

        # 사용자 생성
        user = User(
            email=email, is_approved=False, is_admin=False  # 기본 상태: pending
        )
        user.set_password(password)

        try:
            db.session.add(user)
            db.session.commit()
            flash(
                "회원가입이 완료되었습니다. 관리자 승인 후 로그인할 수 있습니다.",
                "success",
            )
            return redirect(url_for("auth.login"))
        except Exception as e:
            db.session.rollback()
            flash("회원가입 중 오류가 발생했습니다.", "error")
            return render_template("auth/register.html")

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """로그인"""
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        from models.user import User

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember", False) == "on"

        if not email or not password:
            flash("이메일과 비밀번호를 입력해주세요.", "error")
            return render_template("auth/login.html")

        try:
            user = User.query.filter_by(email=email).first()

            if user and user.check_password(password):
                if not user.is_approved:
                    flash(
                        "아직 승인되지 않은 계정입니다. 관리자 승인을 기다려주세요.",
                        "warning",
                    )
                    return render_template("auth/pending.html")

                login_user(user, remember=remember)
                flash(f"환영합니다, {user.email}님!", "success")
                next_page = request.args.get("next")
                return redirect(next_page or url_for("dashboard.index"))
            else:
                flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")
        except RuntimeError as e:
            current_app.logger.error(f"RuntimeError during login: {str(e)}")
            if "not registered" in str(e).lower() or "SQLAlchemy" in str(e):
                flash(
                    "데이터베이스 연결 오류가 발생했습니다. 서버를 재시작해주세요.",
                    "error",
                )
            else:
                flash(f"로그인 중 오류가 발생했습니다: {str(e)}", "error")
            import traceback

            traceback.print_exc()
        except Exception as e:
            current_app.logger.error(f"Exception during login: {str(e)}")
            flash(f"로그인 중 오류가 발생했습니다: {str(e)}", "error")
            import traceback

            traceback.print_exc()

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    """로그아웃"""
    logout_user()
    flash("로그아웃되었습니다.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/pending")
def pending():
    """승인 대기 페이지"""
    return render_template("auth/pending.html")
