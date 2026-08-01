"""재시도 패스는 크롤러가 '차단 해제 대기 중'이면 기다렸다가 재시도한다.

2026-08-01 실측: SSG가 잡 말미에 차단(5분)에 걸린 채로 재시도 패스가 돌아
152건이 회복되지 못했다. 크롤러가 남은 차단 시간을 알려주면(초), 재시도
패스가 한 번만 그만큼 기다린 뒤 진행해 회복률을 높인다.
"""

from utils.crawling_engine_v2 import CrawlingEngineV2


class _BlockedCrawler:
    """처음엔 차단 상태(대기 필요), 대기 후에는 정상 수집."""

    def __init__(self, wait_seconds):
        self._wait = wait_seconds
        self.crawled = []

    def seconds_until_ready(self):
        return self._wait

    def crawl_price(self, url):
        self.crawled.append(url)
        return {"상품 url": url, "결과 상태": "success", "상품 가격": 1000}


def _engine_with_sleep_recorder(crawler):
    engine = CrawlingEngineV2()
    engine._add_log = lambda *a, **k: None
    slept = []
    engine._sleep = lambda seconds: slept.append(seconds)

    import crawlers.crawler_factory as factory

    original = factory.get_crawler_by_url
    factory.get_crawler_by_url = lambda url: crawler
    return engine, slept, factory, original


def _run(engine, results, stats):
    engine._retry_failed_prices(1, results, stats)


class _Stats:
    error_count = 3
    success_count = 0
    sold_out_count = 0
    not_found_count = 0


def _results(n):
    return [
        {"prices": [{"결과 상태": "error", "상품 url": f"http://ssg/{i}", "seller": "s"}]}
        for i in range(n)
    ]


def test_waits_once_for_block_to_expire():
    crawler = _BlockedCrawler(wait_seconds=40)
    engine, slept, factory, original = _engine_with_sleep_recorder(crawler)
    try:
        _run(engine, _results(3), _Stats())
    finally:
        factory.get_crawler_by_url = original
    assert slept == [40]              # 크롤러당 한 번만 대기
    assert len(crawler.crawled) == 3  # 대기 후 전부 재시도


def test_no_wait_when_not_blocked():
    crawler = _BlockedCrawler(wait_seconds=0)
    engine, slept, factory, original = _engine_with_sleep_recorder(crawler)
    try:
        _run(engine, _results(2), _Stats())
    finally:
        factory.get_crawler_by_url = original
    assert slept == []


def test_wait_is_capped():
    crawler = _BlockedCrawler(wait_seconds=99999)
    engine, slept, factory, original = _engine_with_sleep_recorder(crawler)
    try:
        _run(engine, _results(1), _Stats())
    finally:
        factory.get_crawler_by_url = original
    assert slept == [CrawlingEngineV2.RETRY_MAX_BLOCK_WAIT]
