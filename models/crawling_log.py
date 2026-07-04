from database import db
from datetime import datetime, timezone, timedelta

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))


def get_kst_now():
    return datetime.now(KST)


class CrawlingLog(db.Model):
    """크롤링 로그 모델"""

    __tablename__ = "crawling_logs"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(
        db.Integer, db.ForeignKey("crawling_jobs.id"), nullable=False, index=True
    )
    level = db.Column(db.String(20), nullable=False)  # 'INFO', 'WARNING', 'ERROR'
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=get_kst_now, nullable=False, index=True)

    def __repr__(self):
        return f"<CrawlingLog {self.id}: {self.level} - {self.message[:50]}>"
