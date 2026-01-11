import os
from pathlib import Path

basedir = Path(__file__).parent.absolute()


class Config:
    """기본 설정"""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-in-production"

    # 데이터베이스
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or f"sqlite:///{basedir}/crawling.db?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {
            "check_same_thread": False,
        },
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # JSON 인코딩 설정
    JSON_AS_ASCII = False
    JSON_SORT_KEYS = False

    # Flask-Login
    REMEMBER_COOKIE_DURATION = 86400  # 1일

    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URL = os.environ.get("REDIS_URL") or "memory://"

    # 크롤링 설정 (4GB RAM, 2 vCPU 환경 최적화)
    MAX_CONCURRENT_JOBS_PER_USER = int(
        os.environ.get("MAX_CONCURRENT_JOBS_PER_USER", 5)
    )
    MAX_CONCURRENT_JOBS_SYSTEM = int(os.environ.get("MAX_CONCURRENT_JOBS_SYSTEM", 5))
    
    # 크롤링 성능 설정
    CRAWLING_BATCH_SIZE = int(os.environ.get("CRAWLING_BATCH_SIZE", 10))
    CRAWLING_MAX_WORKERS = int(os.environ.get("CRAWLING_MAX_WORKERS", 2))

    # 구글 시트 API
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    # Celery (선택사항)
    CELERY_BROKER_URL = (
        os.environ.get("CELERY_BROKER_URL") or "redis://localhost:6379/0"
    )
    CELERY_RESULT_BACKEND = (
        os.environ.get("CELERY_RESULT_BACKEND") or "redis://localhost:6379/0"
    )

    # 로깅
    LOG_DIR = basedir / "logs"
    LOG_DIR.mkdir(exist_ok=True)


class DevelopmentConfig(Config):
    """개발 환경 설정"""

    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """운영 환경 설정"""

    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32)


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
