"""워밍업 브라우저가 프록시를 타는지 + 그 IP로 SSG가 열리는지 확인.

사용법:
    venv/bin/python scripts/diag_ssg_browser_proxy.py

HTTP 요청(diag_proxy.py)은 프록시를 타는 게 확인됐지만, 브라우저까지
같은 IP로 나가는지는 별개다. 브라우저의 실제 출구 IP를 먼저 찍고,
같은 브라우저로 SSG 상품 페이지를 시도해 원인을 좁힌다.

판정:
  출구 IP가 서버 IP  → 브라우저에 프록시가 적용되지 않음 (설정 문제)
  출구 IP가 프록시 IP + 상품 200 → 해결
  출구 IP가 프록시 IP + 상품 403 → IP가 아니라 브라우저 지문 문제
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from crawlers.ssg_crawler import SSGCrawler  # noqa: E402

MAIN = SSGCrawler.WARMUP_MAIN_URL
ITEM = SSGCrawler.WARMUP_ITEM_URL


def probe(page, result):
    page.goto("https://api.ipify.org/?format=json")
    page.wait_for_timeout(1500)
    result["browser_ip"] = page.inner_text("body")[:60]
    print(f"브라우저 출구 IP: {result['browser_ip']}")

    page.goto(MAIN)
    page.wait_for_timeout(3000)
    print(f"SSG 메인: HTML {len(page.content()):,}B")
    for x, y in ((200, 300), (400, 350), (600, 500)):
        page.mouse.move(x, y)
        page.wait_for_timeout(400)
    page.mouse.wheel(0, 700)
    page.wait_for_timeout(3000)

    page.goto(ITEM)
    page.wait_for_timeout(4000)
    html = page.content()
    result["item_ok"] = "ssg_price" in html
    print(f"SSG 상품: HTML {len(html):,}B, 가격 {'있음' if result['item_ok'] else '없음'}")
    return page


def main():
    proxy = SSGCrawler._proxy()
    print(f"프록시 설정: {'있음' if proxy else '없음 (직결)'}\n")

    SSGCrawler._ensure_virtual_display()
    from scrapling.fetchers import StealthySession

    result = {}
    session = StealthySession(**SSGCrawler._warmup_session_kwargs())
    session.start()
    try:
        session.fetch(MAIN, page_action=lambda page: probe(page, result))
    finally:
        session.close()

    print("\n--- 판정 ---")
    if result.get("item_ok"):
        print("✅ 프록시 경유로 SSG 상품 페이지 열림 — 크롤러가 정상 동작해야 합니다")
    elif proxy and "61." not in result.get("browser_ip", "") and "\"ip\"" in result.get(
        "browser_ip", ""
    ):
        print("⚠️ 브라우저 출구 IP를 위에서 확인하세요 —")
        print("   HTTP(diag_proxy.py) IP와 다르면 브라우저에 프록시가 안 걸린 것")
    else:
        print("⛔ 프록시 IP로도 상품 403 → IP가 아니라 브라우저 지문 문제")
        print("   (서버는 GPU가 없어 WebGL이 소프트웨어 렌더러로 노출됨)")


if __name__ == "__main__":
    main()
