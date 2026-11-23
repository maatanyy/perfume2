"""URL/사이트 → 크롤러 라우팅 테스트 (crawler_factory가 단일 출처)"""

import pytest

from crawlers import crawler_factory
from crawlers.crawler_factory import (
    SITES, crawler_class_for_url, get_crawler, get_crawler_by_url,
)
from crawlers.ssg_crawler import SSGCrawler
from crawlers.cj_crawler import CJCrawler
from crawlers.shinsegae_crawler import ShinsegaeCrawler
from crawlers.lotte_crawler import LotteCrawler
from crawlers.gs_crawler import GSCrawler
from utils.crawling_engine_v2 import CrawlingEngineV2


# 과거 결과 파일에 실제로 등장한 호스트들
@pytest.mark.parametrize("url, expected", [
    ("https://www.ssg.com/item/itemView.ssg?itemId=1", SSGCrawler),
    ("https://ssg.com/item/itemView.ssg?itemId=1", SSGCrawler),
    ("https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1", SSGCrawler),
    ("https://department.ssg.com/item/itemView.ssg?itemId=1", SSGCrawler),
    ("https://www.shinsegaetvshopping.com/display/detail/1", ShinsegaeCrawler),
    ("https://display.cjonstyle.com/p/item/1", CJCrawler),
    ("https://www.lotteimall.com/goods/viewGoodsDetail.lotte?goods_no=1", LotteCrawler),
    ("https://www.gsshop.com/prd/prd.gs?prdid=1", GSCrawler),
    ("HTTPS://WWW.GSSHOP.COM/prd/prd.gs?prdid=1", GSCrawler),
])
def test_url_routes_to_site_crawler(url, expected):
    assert crawler_class_for_url(url) is expected
    assert isinstance(get_crawler_by_url(url), expected)


@pytest.mark.parametrize("url", ["", None, "https://www.11st.co.kr/products/1"])
def test_unsupported_url_returns_none(url):
    assert crawler_class_for_url(url) is None
    assert get_crawler_by_url(url) is None


@pytest.mark.parametrize("site, expected", [
    ("ssg", SSGCrawler),
    ("cj", CJCrawler),
    ("ssg_shoping", ShinsegaeCrawler),
    ("롯데아이몰", LotteCrawler),
    ("gs", GSCrawler),
])
def test_site_key_routes_to_crawler(site, expected):
    assert isinstance(get_crawler(site), expected)


def test_every_site_has_crawler():
    assert set(SITES) == {"ssg", "cj", "ssg_shoping", "롯데아이몰", "gs"}
    for key in SITES:
        assert get_crawler(key) is not None


def test_unknown_site_returns_none():
    assert get_crawler("unknown") is None


class _Recorder:
    """crawl_price 호출을 기록하는 가짜 크롤러"""
    instances = []

    def __init__(self):
        self.urls = []
        _Recorder.instances.append(self)

    def crawl_price(self, url):
        self.urls.append(url)
        return {"상품 url": url, "상품 가격": 1000, "결과 상태": "success"}


def test_engine_uses_factory_routing_and_falls_back_to_default(monkeypatch):
    """엔진은 팩토리 라우팅을 쓰고, 미지원 도메인은 잡의 기본 크롤러로 시도한다."""
    _Recorder.instances = []
    monkeypatch.setattr(
        crawler_factory, "DOMAIN_CRAWLERS", [("gsshop.com", _Recorder)]
    )
    default = _Recorder()
    product = {
        "product_name": "향수",
        "waffle": {"url": "https://www.gsshop.com/prd/1"},
        "competitors": [
            {"name": "11번가", "url": "https://www.11st.co.kr/products/1"},
            {"name": "GS", "url": "https://www.gsshop.com/prd/2"},
        ],
    }

    result = CrawlingEngineV2()._crawl_product(product, default)

    assert result["result_status"] == "success"
    assert default.urls == ["https://www.11st.co.kr/products/1"]
    routed = [r for r in _Recorder.instances if r is not default]
    assert len(routed) == 1  # 같은 스레드에서는 크롤러 인스턴스 재사용
    assert routed[0].urls == [
        "https://www.gsshop.com/prd/1", "https://www.gsshop.com/prd/2",
    ]
