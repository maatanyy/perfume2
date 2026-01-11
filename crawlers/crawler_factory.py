"""크롤러 팩토리"""

from typing import Optional, Dict
from crawlers.base_crawler import BaseCrawler
from crawlers.ssg_crawler import SSGCrawler
from crawlers.cj_crawler import CJCrawler
from crawlers.shinsegae_crawler import ShinsegaeCrawler
from crawlers.lotte_crawler import LotteCrawler
from crawlers.gs_crawler import GSCrawler

# 크롤러 인스턴스 캐시 (프로세스 레벨 - 메모리 절약)
_crawler_instances: Dict[str, BaseCrawler] = {}


def get_crawler(site_name: str) -> Optional[BaseCrawler]:
    """사이트명에 따라 적절한 크롤러 반환 (캐싱)"""
    site_lower = site_name.lower()

    # 캐시 확인
    if site_lower in _crawler_instances:
        return _crawler_instances[site_lower]

    # 새 인스턴스 생성 및 캐싱
    crawler = None
    if (
        "ssg" in site_lower
        and "shopping" not in site_lower
        and "shoping" not in site_lower
    ):
        crawler = SSGCrawler()
    elif "cj" in site_lower or "cjonstyle" in site_lower:
        crawler = CJCrawler()
    elif (
        "ssg_shoping" in site_lower
        or "shinsegaetvshopping" in site_lower
        or "신세계" in site_lower
    ):
        crawler = ShinsegaeCrawler()
    elif "롯데" in site_lower or "lotte" in site_lower or "lotteimall" in site_lower:
        crawler = LotteCrawler()
    elif "gs" in site_lower or "gsshop" in site_lower:
        crawler = GSCrawler()

    if crawler:
        _crawler_instances[site_lower] = crawler

    return crawler


def get_crawler_by_url(url: str) -> Optional[BaseCrawler]:
    """URL에 따라 적절한 크롤러 반환 (캐싱)"""
    if not url:
        return None

    url_lower = url.lower()

    # 도메인 추출
    domain = None
    if "ssg.com" in url_lower and "shinsegaetvshopping.com" not in url_lower:
        domain = "ssg.com"
    elif "cjonstyle.com" in url_lower:
        domain = "cjonstyle.com"
    elif "shinsegaetvshopping.com" in url_lower:
        domain = "shinsegaetvshopping.com"
    elif "lotteimall.com" in url_lower:
        domain = "lotteimall.com"
    elif "gsshop.com" in url_lower:
        domain = "gsshop.com"

    if not domain:
        return None

    # 캐시 확인
    if domain in _crawler_instances:
        return _crawler_instances[domain]

    # 새 인스턴스 생성 및 캐싱
    crawler = None
    if domain == "ssg.com":
        crawler = SSGCrawler()
    elif domain == "cjonstyle.com":
        crawler = CJCrawler()
    elif domain == "shinsegaetvshopping.com":
        crawler = ShinsegaeCrawler()
    elif domain == "lotteimall.com":
        crawler = LotteCrawler()
    elif domain == "gsshop.com":
        crawler = GSCrawler()

    if crawler:
        _crawler_instances[domain] = crawler

    return crawler
