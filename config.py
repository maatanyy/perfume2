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

    # 동시 실행 잡 상한 (사용자별 / 시스템 전체)
    MAX_CONCURRENT_JOBS_PER_USER = int(os.environ.get("MAX_CONCURRENT_JOBS_PER_USER", 5))
    MAX_CONCURRENT_JOBS_SYSTEM = int(os.environ.get("MAX_CONCURRENT_JOBS_SYSTEM", 10))

    # 잡 하나의 배치 크기 / 동시 워커 수
    CRAWLING_BATCH_SIZE = int(os.environ.get("CRAWLING_BATCH_SIZE", 10))
    CRAWLING_MAX_WORKERS = int(os.environ.get("CRAWLING_MAX_WORKERS", 5))

    # 앱 프로세스 RSS 기준 메모리 경고/위험 임계값 (도달 시 GC 실행)
    MEMORY_WARNING_THRESHOLD_MB = int(os.environ.get("MEMORY_WARNING_THRESHOLD_MB", 2500))
    MEMORY_CRITICAL_THRESHOLD_MB = int(os.environ.get("MEMORY_CRITICAL_THRESHOLD_MB", 3200))

    LOG_DIR = basedir / "logs"
    LOG_DIR.mkdir(exist_ok=True)


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32)


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
