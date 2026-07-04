from database import db
from datetime import datetime, timezone, timedelta

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))


def get_kst_now():
    return datetime.now(KST)


class CrawlingJob(db.Model):
    """크롤링 작업 모델"""

    __tablename__ = "crawling_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    site_name = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    # status: 'pending', 'running', 'paused', 'completed', 'failed', 'cancelled'

    progress = db.Column(db.Integer, default=0)  # 0-100
    total_items = db.Column(db.Integer)
    processed_items = db.Column(db.Integer, default=0)

    google_sheet_url = db.Column(db.String(500))
    sheet_name = db.Column(db.String(100))
    result_file = db.Column(db.String(500))  # 결과 파일 경로

    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    error_message = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=get_kst_now, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=get_kst_now, onupdate=get_kst_now, nullable=False
    )

    # 관계
    logs = db.relationship(
        "CrawlingLog", backref="job", lazy="dynamic", cascade="all, delete-orphan"
    )

    def update_progress(self, processed, total):
        """진행률 업데이트"""
        self.processed_items = processed
        self.total_items = total
        if total > 0:
            self.progress = int((processed / total) * 100)
        else:
            self.progress = 0
        self.updated_at = get_kst_now()
        db.session.commit()

    def start(self):
        """작업 시작"""
        self.status = "running"
        self.started_at = get_kst_now()
        self.updated_at = get_kst_now()
        db.session.commit()

    def complete(self):
        """작업 완료"""
        self.status = "completed"
        self.completed_at = get_kst_now()
        self.progress = 100
        self.updated_at = get_kst_now()
        db.session.commit()

    def fail(self, error_message):
        """작업 실패"""
        self.status = "failed"
        self.error_message = error_message
        self.completed_at = get_kst_now()
        self.updated_at = get_kst_now()
        db.session.commit()

    def cancel(self):
        """작업 취소"""
        self.status = "cancelled"
        self.completed_at = get_kst_now()
        self.updated_at = get_kst_now()
        db.session.commit()

    def __repr__(self):
        return f"<CrawlingJob {self.id}: {self.site_name} - {self.status}>"
