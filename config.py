import os
from pathlib import Path

basedir = Path(__file__).parent.absolute()


class Config:
    """기본 설정"""

    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-in-production"

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL")
        or f"sqlite:///{basedir}/crawling.db?charset=utf8mb4"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    JSON_AS_ASCII = False
    JSON_SORT_KEYS = False

    REMEMBER_COOKIE_DURATION = 86400

    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URL = os.environ.get("REDIS_URL") or "memory://"

    # 크롤링 설정 (8GB RAM, 4 vCPU 서버 기준)
    MAX_CONCURRENT_JOBS_PER_USER = int(os.environ.get("MAX_CONCURRENT_JOBS_PER_USER", 5))
    MAX_CONCURRENT_JOBS_SYSTEM = int(os.environ.get("MAX_CONCURRENT_JOBS_SYSTEM", 10))

    # workers 5로 확장 (5개 사이트 동시)
    CRAWLING_BATCH_SIZE = int(os.environ.get("CRAWLING_BATCH_SIZE", 10))
    CRAWLING_MAX_WORKERS = int(os.environ.get("CRAWLING_MAX_WORKERS", 5))

    # 브라우저 풀: 5개로 확장
    BROWSER_POOL_MAX_BROWSERS = int(os.environ.get("BROWSER_POOL_MAX_BROWSERS", 5))
    BROWSER_POOL_MAX_REQUESTS = int(os.environ.get("BROWSER_POOL_MAX_REQUESTS", 30))
    BROWSER_POOL_MAX_AGE_SECONDS = int(os.environ.get("BROWSER_POOL_MAX_AGE_SECONDS", 300))

    # 메모리 모니터링 (8GB 서버 기준)
    MEMORY_WARNING_THRESHOLD_MB = int(os.environ.get("MEMORY_WARNING_THRESHOLD_MB", 5500))
    MEMORY_CRITICAL_THRESHOLD_MB = int(os.environ.get("MEMORY_CRITICAL_THRESHOLD_MB", 7000))

    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
    GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")

    LOG_DIR = basedir / "logs"
    LOG_DIR.mkdir(exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False
    # 로컬 개발 시 메모리 임계값 낮춤
    MEMORY_WARNING_THRESHOLD_MB = 2500
    MEMORY_CRITICAL_THRESHOLD_MB = 3200


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32)


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
