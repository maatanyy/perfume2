"""엔진 실패 재시도 패스 테스트

실전(2026-07-25): 롯데 45건이 크롤링 도중 일시 403 차단으로 '오류'가 됐지만,
시간이 지나 재시도하면 전부 성공했다. 잡 말미에 error 항목을 한 번 더
시도하는 재시도 패스로 이런 일시 실패를 회복한다.
"""

from utils.crawling_engine_v2 import CrawlingEngineV2, JobStats


class _StubCrawler:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def crawl_price(self, url):
        self.calls.append(url)
        return dict(self.result)


def _engine():
    e = CrawlingEngineV2()
    e._add_log = lambda *a, **k: None  # DB 로그 차단
    return e


def _error_results():
    return [{
        "product_name": "테스트향수",
        "prices": [
            {"seller": "waffle", "상품 url": "http://t/1",
             "결과 상태": "error", "에러 발생": "페이지를 가져올 수 없습니다."},
            {"seller": "경쟁사A", "상품 url": "",
             "결과 상태": "error", "에러 발생": "URL 없음"},
            {"seller": "경쟁사B", "상품 url": "http://t/2",
             "결과 상태": "success", "판매가": 5000},
        ],
        "result_status": "error",
    }]


def test_retry_pass_recovers_transient_errors(monkeypatch):
    """error 항목만 재시도해 성공으로 교체하고 통계를 갱신한다.
    URL 없는 항목과 이미 성공한 항목은 재시도하지 않는다."""
    stub = _StubCrawler({
        "상품 url": "http://t/1", "결과 상태": "success",
        "판매가": 31920, "상품 가격": 31920,
    })
    monkeypatch.setattr(
        "crawlers.crawler_factory.get_crawler_by_url", lambda url: stub
    )
    engine = _engine()
    stats = JobStats()
    stats.error_count = 2
    results = _error_results()

    engine._retry_failed_prices(1, results, stats)

    assert stub.calls == ["http://t/1"]
    entry = results[0]["prices"][0]
    assert entry["결과 상태"] == "success"
    assert entry["판매가"] == 31920
    assert entry["seller"] == "waffle"  # seller 정보 유지
    assert stats.error_count == 1  # URL 없음 건은 회복 불가로 남음
    assert stats.success_count == 1


def test_retry_pass_keeps_original_when_retry_fails(monkeypatch):
    """재시도도 실패하면 원래 항목과 통계를 그대로 둔다."""
    stub = _StubCrawler({
        "상품 url": "http://t/1", "결과 상태": "error",
        "에러 발생": "여전히 차단",
    })
    monkeypatch.setattr(
        "crawlers.crawler_factory.get_crawler_by_url", lambda url: stub
    )
    engine = _engine()
    stats = JobStats()
    stats.error_count = 2
    results = _error_results()

    engine._retry_failed_prices(1, results, stats)

    entry = results[0]["prices"][0]
    assert entry["결과 상태"] == "error"
    assert entry["에러 발생"] == "페이지를 가져올 수 없습니다."
    assert stats.error_count == 2
    assert stats.success_count == 0


def test_retry_pass_respects_cancellation(monkeypatch):
    """취소된 잡은 재시도 패스를 돌지 않는다."""
    stub = _StubCrawler({"상품 url": "http://t/1", "결과 상태": "success"})
    monkeypatch.setattr(
        "crawlers.crawler_factory.get_crawler_by_url", lambda url: stub
    )
    engine = _engine()
    engine.job_cancelled[1] = True
    stats = JobStats()
    results = _error_results()

    engine._retry_failed_prices(1, results, stats)

    assert stub.calls == []
