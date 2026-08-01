from dotenv import load_dotenv

# config를 읽기 전에 .env를 환경변수로 올린다 — 이 호출이 없으면 .env에
# 적어둔 설정(SSG_PROXY 등)이 조용히 무시된다 (2026-08-01 실측).
load_dotenv()

from flask import Flask  # noqa: E402
from flask_login import LoginManager  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
from config import config  # noqa: E402
from database import db  # noqa: E402
import os  # noqa: E402
import logging  # noqa: E402
import atexit  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

login_manager = LoginManager()
limiter = Limiter(
    key_func=get_remote_address, default_limits=["200 per day", "50 per hour"]
)


def create_app(config_name=None):
    """Flask 앱 팩토리"""
    app = Flask(__name__)

    config_name = config_name or os.environ.get("FLASK_ENV", "development")
    app.config.from_object(config[config_name])

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "로그인이 필요합니다."
    login_manager.login_message_category = "info"
    limiter.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from flask import has_app_context
        from models.user import User
        if not has_app_context():
            return None
        try:
            user_id_int = int(user_id) if isinstance(user_id, str) else user_id
            return User.query.get(user_id_int)
        except (ValueError, TypeError, Exception):
            return None

    from routes.auth import auth_bp
    from routes.dashboard import dashboard_bp
    from routes.admin import admin_bp
    from routes.api import api_bp

    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.route("/")
    def index():
        from flask import redirect, url_for
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.index"))
        return redirect(url_for("auth.login"))

    # SQLite WAL 모드 활성화 (동시 읽기/쓰기 허용)
    with app.app_context():
        try:
            from sqlalchemy import event, text
            from database import db as _db
            @event.listens_for(_db.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=10000")
                cursor.close()
        except Exception as e:
            logger.warning(f"SQLite WAL 설정 실패: {e}")

    # 크롤링 엔진 v2 초기화
    from utils.crawling_engine_v2 import get_crawling_engine_v2
    engine_v2 = get_crawling_engine_v2()
    engine_v2.set_app(app)
    logger.info("✅ 크롤링 엔진 v2 초기화 완료 (브라우저 세마포어: 5)")

    def cleanup():
        logger.info("🧹 앱 종료 - 리소스 정리 중...")
        try:
            engine_v2.shutdown()
        except Exception as e:
            logger.error(f"크롤링 엔진 종료 오류: {e}")

    atexit.register(cleanup)

    @app.after_request
    def after_request(response):
        # SSE 응답은 Content-Type 덮어쓰기 금지
        if "text/event-stream" not in response.content_type:
            response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response

    return app


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        from models.user import User
        from models.crawling_job import CrawlingJob
        from models.crawling_log import CrawlingLog
        db.create_all()
        logger.info("✅ 데이터베이스 테이블 확인 완료")

        # 서버 재시작 시 좀비 job 정리 (엔진이 추적하지 않는 stale job)
        stale_jobs = CrawlingJob.query.filter(
            CrawlingJob.status.in_(["running", "pending"])
        ).all()
        if stale_jobs:
            for job in stale_jobs:
                job.fail("서버 재시작으로 인해 중단됨")
            db.session.commit()
            logger.info(f"🧹 좀비 잡 {len(stale_jobs)}개 정리 완료")

    logger.info("🚀 서버 시작: http://localhost:5001")
    app.run(debug=True, host="0.0.0.0", port=5001)
