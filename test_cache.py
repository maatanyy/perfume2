#!/usr/bin/env python3
"""크롤러 캐시 테스트"""
import sys

sys.path.insert(0, "/Users/nohminsung/Desktop/perfume2")

from crawlers.crawler_factory import get_crawler_by_url, _crawler_instances

# 같은 URL 5번 호출
urls = [
    "https://www.ssg.com/item/1",
    "https://www.ssg.com/item/2",
    "https://www.cjonstyle.com/item/1",
    "https://www.ssg.com/item/3",
    "https://www.cjonstyle.com/item/2",
]

print("=== 크롤러 인스턴스 테스트 ===")
crawlers = []
for i, url in enumerate(urls, 1):
    crawler = get_crawler_by_url(url)
    crawlers.append(crawler)
    print(f"{i}. {url[:40]:<40} → {crawler.__class__.__name__} (id: {id(crawler)})")

print(f"\n=== 캐시 상태 ===")
print(f"캐시 크기: {len(_crawler_instances)}")
for domain, crawler in _crawler_instances.items():
    print(f"  {domain}: {crawler.__class__.__name__} (id: {id(crawler)})")

print(f"\n=== 재사용 확인 ===")
print(f"SSG 인스턴스 ID: {id(crawlers[0])}, {id(crawlers[1])}, {id(crawlers[3])}")
print(f"재사용 여부: {crawlers[0] is crawlers[1] is crawlers[3]}")
print(f"CJ 인스턴스 ID: {id(crawlers[2])}, {id(crawlers[4])}")
print(f"재사용 여부: {crawlers[2] is crawlers[4]}")
