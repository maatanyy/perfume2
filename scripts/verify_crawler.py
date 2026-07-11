"""실제 상품 페이지로 크롤러 추출 결과를 검증하는 CLI.

사용법:
    perfume/bin/python scripts/verify_crawler.py <상품URL> [<상품URL> ...]

출력: 판매가/쿠폰적용가/배송비/최종가격/결과상태 JSON
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.crawler_factory import get_crawler_by_url


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    for url in sys.argv[1:]:
        crawler = get_crawler_by_url(url)
        if not crawler:
            print(f"\n지원하지 않는 URL: {url}")
            continue
        print(f"\n=== [{crawler.__class__.__name__}] {url[:80]}")
        try:
            result = crawler.crawl_price(url, auto_close=True)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"오류: {e}")


if __name__ == "__main__":
    main()
