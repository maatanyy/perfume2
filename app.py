from flask import Flask
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import config
from database import db
import os

# 확장 초기화 (모듈 레벨에서 생성)
login_manager = LoginManager()
limiter = Limiter(
    key_func=get_remote_address, default_limits=["200 per day", "50 per hour"]
)


def create_app(config_name=None):
    """Flask 앱 팩토리"""
    app = Flask(__name__)

    # 설정 로드
    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    app.config.from_object(config[config_name])

    # 확장 초기화 (반드시 먼저 실행)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "로그인이 필요합니다."
    login_manager.login_message_category = "info"
    limiter.init_app(app)

    # 사용자 로더 (모델 import 전에 정의)
    @login_manager.user_loader
    def load_user(user_id):
        from flask import has_app_context
        from models.user import User

        # 앱 컨텍스트 확인
        if not has_app_context():
            return None

        try:
            # user_id가 문자열일 수 있으므로 int 변환
            user_id_int = int(user_id) if isinstance(user_id, str) else user_id
            return User.query.get(user_id_int)
        except (ValueError, TypeError, Exception):
            return None

    # 블루프린트 등록 (db.init_app 이후에 import)
    # 블루프린트가 import될 때 모델도 함께 import됨
    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.admin import admin_bp
    from routes.api import api_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")

    # 메인 라우트
    @app.route("/")
    def index():
        from flask import redirect, url_for
        from flask_login import current_user

        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    # 크롤링 엔진에 앱 설정 (백그라운드 스레드에서 사용하기 위해)
    from utils.crawling_engine import crawling_engine

    crawling_engine.set_app(app)

    # 응답 헤더에 UTF-8 설정
    @app.after_request
    def after_request(response):
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response

    return app


if __name__ == "__main__":
    app = create_app()

    # 데이터베이스 테이블이 없으면 생성
    with app.app_context():
        # 모든 모델을 import해야 db.create_all()이 제대로 작동함
        from models.user import User
        from models.crawling_job import CrawlingJob
        from models.crawling_log import CrawlingLog

        db.create_all()
        print("✅ 데이터베이스 테이블 확인 완료")

    app.run(debug=True, host="0.0.0.0", port=5001)
