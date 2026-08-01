"""잡 종료 시 브라우저 정리가 다른 잡을 방해하지 않아야 한다.

2026-08-01 발견: 잡 종료(및 취소) 시 서버의 모든 chrome/chromium 프로세스를
SIGKILL한다. 5개 사이트를 동시에 돌리면 먼저 끝난 잡이 아직 실행 중인 CJ의
브라우저를 죽여, CJ가 세션을 재생성하는 동안 요청이 실패한다.
→ 실행 중인 다른 잡이 없을 때만 정리해야 한다.
"""

from utils.crawling_engine_v2 import CrawlingEngineV2


def _engine_with_active(job_ids):
    engine = CrawlingEngineV2()
    for jid in job_ids:
        engine.active_jobs[jid] = object()
    return engine


def test_cleanup_skipped_while_other_jobs_running():
    engine = _engine_with_active([1, 2])
    assert engine._should_cleanup_browsers(exclude_job_id=1) is False


def test_cleanup_runs_when_last_job_finishes():
    engine = _engine_with_active([1])
    assert engine._should_cleanup_browsers(exclude_job_id=1) is True


def test_cleanup_runs_when_no_jobs_tracked():
    engine = _engine_with_active([])
    assert engine._should_cleanup_browsers(exclude_job_id=99) is True
