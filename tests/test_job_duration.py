"""완료 잡 소요시간 표시 테스트 (started_at ~ completed_at)"""

from datetime import datetime

import models.crawling_log  # noqa: F401 — CrawlingJob 관계(CrawlingLog) 해석에 필요
from models.crawling_job import CrawlingJob


def test_duration_display_minutes_seconds():
    j = CrawlingJob()
    j.started_at = datetime(2026, 7, 25, 10, 0, 0)
    j.completed_at = datetime(2026, 7, 25, 10, 32, 15)
    assert j.duration_display == "32분 15초"


def test_duration_display_hours():
    j = CrawlingJob()
    j.started_at = datetime(2026, 7, 25, 10, 0, 0)
    j.completed_at = datetime(2026, 7, 25, 11, 5, 30)
    assert j.duration_display == "1시간 5분"


def test_duration_display_seconds_only():
    j = CrawlingJob()
    j.started_at = datetime(2026, 7, 25, 10, 0, 0)
    j.completed_at = datetime(2026, 7, 25, 10, 0, 42)
    assert j.duration_display == "42초"


def test_duration_display_empty_when_unfinished():
    j = CrawlingJob()
    j.started_at = datetime(2026, 7, 25, 10, 0, 0)
    j.completed_at = None
    assert j.duration_display == ""
