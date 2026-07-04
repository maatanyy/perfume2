from app import create_app
from models.user import User
from models.crawling_job import CrawlingJob
from models.crawling_log import CrawlingLog
from database import db

app = create_app()

with app.app_context():
    db.create_all()
    stale_jobs = CrawlingJob.query.filter(
        CrawlingJob.status.in_(["running", "pending"])
    ).all()
    if stale_jobs:
        for job in stale_jobs:
            job.fail("서버 재시작으로 인해 중단됨")
        db.session.commit()
