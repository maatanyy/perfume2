"""서버에서 CJ 렌더 결과를 직접 확인하는 진단 스크립트.

사용: venv/bin/python scripts/diag_cj.py [상품URL]
(URL 생략 시 로컬 검증에서 성공했던 상품으로 진단)
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.cj_crawler import CJCrawler

url = sys.argv[1] if len(sys.argv) > 1 else "https://display.cjonstyle.com/p/item/2036483811"

c = CJCrawler()
t0 = time.monotonic()
html = c.fetch_page(url)
elapsed = round(time.monotonic() - t0, 1)

print(f"URL: {url}")
print(f"소요: {elapsed}초")
if html is None:
    print("결과: fetch 실패 (None) — 브라우저 예외 또는 HTTP 오류")
    sys.exit(0)

title = re.search(r"<title>(.*?)</title>", html, re.S)
print(f"HTML 길이: {len(html)}")
print(f"title: {title.group(1).strip() if title else '(없음)'}")
print(f"ff_price 등장 횟수: {html.count('ff_price')}")
print(f"품절 표시: {('btn_soldout' in html) or ('soldout_layer' in html)}")
result = c.extract_price(html, url)
print(f"추출 결과: 상태={result['결과 상태']}, 판매가={result['판매가']}")
