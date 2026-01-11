"""크롤러 팩토리"""

from typing import Optional, Dict
from crawlers.base_crawler import BaseCrawler
from crawlers.ssg_crawler import SSGCrawler
from crawlers.cj_crawler import CJCrawler
from crawlers.shinsegae_crawler import ShinsegaeCrawler
from crawlers.lotte_crawler import LotteCrawler
from crawlers.gs_crawler import GSCrawler

# 크롤러 클래스 매핑 (인스턴스 생성 X, 클래스만 저장)
_crawler_classes: Dict[str, type] = {
    "ssg.com": SSGCrawler,
    "cjonstyle.com": CJCrawler,
    "shinsegaetvshopping.com": ShinsegaeCrawler,
    "lotteimall.com": LotteCrawler,
    "gsshop.com": GSCrawler,
}


def get_crawler(site_name: str) -> Optional[BaseCrawler]:
    """사이트명에 따라 적절한 크롤러 반환 (매번 새 인스턴스)"""
    site_lower = site_name.lower()

    # SSG Shopping 우선 체크 (shinsegaetvshopping.com은 SSG Shopping이므로 SSGCrawler 사용)
    if (
        "ssg_shoping" in site_lower
        or "shinsegaetvshopping" in site_lower
    ):
        return SSGCrawler()  # SSG Shopping은 SSG 크롤러 사용
    elif (
        "ssg" in site_lower
        and "shopping" not in site_lower
        and "shoping" not in site_lower
    ):
        return SSGCrawler()
    elif "cj" in site_lower or "cjonstyle" in site_lower:
        return CJCrawler()
    elif "신세계" in site_lower:  # 신세계는 별도 크롤러 사용 (shinsegaetvshopping 제외)
        return ShinsegaeCrawler()
    elif "롯데" in site_lower or "lotte" in site_lower or "lotteimall" in site_lower:
        return LotteCrawler()
    elif "gs" in site_lower or "gsshop" in site_lower:
        return GSCrawler()

    return None


def get_crawler_by_url(url: str) -> Optional[BaseCrawler]:
    """URL에 따라 적절한 크롤러 반환 (매번 새 인스턴스 - 스레드별 캐시에서 관리)"""
    if not url:
        return None

    url_lower = url.lower()

    # 도메인 추출 및 크롤러 생성 (SSG Shopping 우선 체크)
    # shinsegaetvshopping.com은 SSG Shopping이므로 SSGCrawler 사용
    if "shinsegaetvshopping.com" in url_lower:
        return SSGCrawler()  # SSG Shopping은 SSG 크롤러 사용
    elif "ssg.com" in url_lower:
        return SSGCrawler()
    elif "cjonstyle.com" in url_lower:
        return CJCrawler()
    elif "lotteimall.com" in url_lower:
        return LotteCrawler()
    elif "gsshop.com" in url_lower:
        return GSCrawler()

    return None
