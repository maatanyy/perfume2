"""신세계TV쇼핑 추출실패 원인 진단 (서버에서 실행).

사용법:
    venv/bin/python scripts/diag_shinsegae.py

같은 URL을 두 방식으로 받아 비교한다:
  A) requests (현재 크롤러 방식)
  B) curl_cffi chrome 위장 (SSG에서 효과를 본 방식)

가격 마크업이 A에는 없고 B에는 있으면 TLS 지문 차별 → B로 교체하면 해결.
둘 다 없으면 IP 기반 차별이거나 사이트 DOM 변경이다.
"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from crawlers.shinsegae_crawler import ShinsegaeCrawler  # noqa: E402

URLS = [
    "https://www.shinsegaetvshopping.com/display/detail/48658428",
    "https://www.shinsegaetvshopping.com/display/detail/30124961",
]

PRICE_MARKERS = ("_salePrice", "salePrice", "판매가")


def _summary(html):
    if not html:
        return "응답 없음"
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    found = [m for m in PRICE_MARKERS if m in html]
    return (
        f"{len(html):,}B | title={title.group(1).strip()[:25]!r} "
        f"| 가격흔적={found or '없음'}"
    )


def main():
    crawler = ShinsegaeCrawler()
    from curl_cffi import requests as cr

    curl_session = cr.Session(impersonate="chrome")

    for url in URLS:
        print(f"\n=== {url.split('/')[-1]}")
        try:
            html_a = crawler.fetch_page(url)
        except Exception as e:
            html_a = None
            print(f"A) requests: 예외 {str(e)[:70]}")
        else:
            print(f"A) requests   : {_summary(html_a)}")

        try:
            resp = curl_session.get(
                url, timeout=20, headers={"Accept-Language": "ko-KR,ko;q=0.9"}
            )
            print(f"B) curl_cffi  : HTTP {resp.status_code} | {_summary(resp.text)}")
            html_b = resp.text if resp.status_code == 200 else None
        except Exception as e:
            html_b = None
            print(f"B) curl_cffi: 예외 {str(e)[:70]}")

        for label, html in (("A", html_a), ("B", html_b)):
            if html:
                result = crawler.extract_price(html, url)
                print(f"   {label} 추출 결과: {result['결과 상태']} / 판매가 {result['판매가']}")


if __name__ == "__main__":
    main()
