"""크롤러 팩토리"""
from typing import Optional
from crawlers.base_crawler import BaseCrawler
from crawlers.ssg_crawler import SSGCrawler
from crawlers.cj_crawler import CJCrawler
from crawlers.shinsegae_crawler import ShinsegaeCrawler
from crawlers.lotte_crawler import LotteCrawler
from crawlers.gs_crawler import GSCrawler

def get_crawler(site_name: str) -> Optional[BaseCrawler]:
    """사이트명에 따라 적절한 크롤러 반환"""
    site_lower = site_name.lower()
    
    if 'ssg' in site_lower and 'shopping' not in site_lower and 'shoping' not in site_lower:
        return SSGCrawler()
    elif 'cj' in site_lower or 'cjonstyle' in site_lower:
        return CJCrawler()
    elif 'ssg_shoping' in site_lower or 'shinsegaetvshopping' in site_lower or '신세계' in site_lower:
        return ShinsegaeCrawler()
    elif '롯데' in site_lower or 'lotte' in site_lower or 'lotteimall' in site_lower:
        return LotteCrawler()
    elif 'gs' in site_lower or 'gsshop' in site_lower:
        return GSCrawler()
    
    # 기본 크롤러 (미지원 사이트)
    return None

def get_crawler_by_url(url: str) -> Optional[BaseCrawler]:
    """URL에 따라 적절한 크롤러 반환"""
    if not url:
        return None
    
    url_lower = url.lower()
    
    if 'ssg.com' in url_lower and 'shinsegaetvshopping.com' not in url_lower:
        return SSGCrawler()
    elif 'cjonstyle.com' in url_lower:
        return CJCrawler()
    elif 'shinsegaetvshopping.com' in url_lower:
        return ShinsegaeCrawler()
    elif 'lotteimall.com' in url_lower:
        return LotteCrawler()
    elif 'gsshop.com' in url_lower:
        return GSCrawler()
    
    return None

