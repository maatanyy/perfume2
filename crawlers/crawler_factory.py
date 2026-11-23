"""크롤러 팩토리 — 사이트/URL → 크롤러 라우팅의 단일 출처"""

from typing import Optional
from crawlers.base_crawler import BaseCrawler
from crawlers.ssg_crawler import SSGCrawler
from crawlers.cj_crawler import CJCrawler
from crawlers.shinsegae_crawler import ShinsegaeCrawler
from crawlers.lotte_crawler import LotteCrawler
from crawlers.gs_crawler import GSCrawler

# 도메인 → 크롤러 클래스. URL에 도메인이 포함되는지로 판별하며 위에서부터
# 검사한다 (shinsegaemall.ssg.com 등 서브도메인도 해당 도메인으로 매칭).
DOMAIN_CRAWLERS = [
    ("shinsegaetvshopping.com", ShinsegaeCrawler),
    ("ssg.com", SSGCrawler),
    ("cjonstyle.com", CJCrawler),
    ("lotteimall.com", LotteCrawler),
    ("gsshop.com", GSCrawler),
]

# 대시보드 사이트 키(= 구글 시트 탭 이름) → 메타 정보
SITES = {
    "ssg": {"label": "SSG.COM", "domain": "ssg.com", "icon": "🛒"},
    "cj": {"label": "CJ온스타일", "domain": "cjonstyle.com", "icon": "📺"},
    "ssg_shoping": {"label": "신세계TV쇼핑", "domain": "shinsegaetvshopping.com", "icon": "🏪"},
    "롯데아이몰": {"label": "롯데아이몰", "domain": "lotteimall.com", "icon": "🎡"},
    "gs": {"label": "GS샵", "domain": "gsshop.com", "icon": "🏬"},
}


def crawler_class_for_url(url: str) -> Optional[type]:
    """URL을 처리할 크롤러 클래스. 지원하지 않는 URL이면 None."""
    url_lower = (url or "").lower()
    for domain, cls in DOMAIN_CRAWLERS:
        if domain in url_lower:
            return cls
    return None


def get_crawler_by_url(url: str) -> Optional[BaseCrawler]:
    """URL에 따라 적절한 크롤러 반환 (매번 새 인스턴스)"""
    cls = crawler_class_for_url(url)
    return cls() if cls else None


def get_crawler(site_name: str) -> Optional[BaseCrawler]:
    """사이트 키(SITES)에 따라 적절한 크롤러 반환 (매번 새 인스턴스)"""
    site = SITES.get(site_name)
    if not site:
        return None
    return get_crawler_by_url(site["domain"])
