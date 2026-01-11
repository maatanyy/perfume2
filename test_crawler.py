"""크롤러 테스트 스크립트"""

from crawlers.ssg_crawler import SSGCrawler
from crawlers.cj_crawler import CJCrawler

# 테스트 URL
ssg_url = "https://www.ssg.com/item/itemView.ssg?itemId=1000602916933"
cj_url = "https://display.cjonstyle.com/p/item/43077989"

print("=" * 60)
print("SSG 크롤링 테스트")
print("=" * 60)
ssg_crawler = SSGCrawler()
try:
    result = ssg_crawler.crawl_price(ssg_url)
    print(f"결과: {result}")
    print(f"가격: {result.get('상품 가격')}")
except Exception as e:
    print(f"에러: {e}")
finally:
    ssg_crawler._close_driver()

print("\n" + "=" * 60)
print("CJ 크롤링 테스트")
print("=" * 60)
cj_crawler = CJCrawler()
try:
    result = cj_crawler.crawl_price(cj_url)
    print(f"결과: {result}")
    print(f"가격: {result.get('상품 가격')}")
except Exception as e:
    print(f"에러: {e}")
finally:
    cj_crawler._close_driver()
