"""SSG 워밍업 정밀 진단 — 서버에서 왜 센서 검증이 실패하는지 판별.

사용법:
    venv/bin/python scripts/diag_ssg_warm.py

출력 해석:
  _abck 마커 '~0~'  → 센서 검증 통과 (쿠키 정상). 그래도 상품이 403이면
                      IP 평판(데이터센터 IP) 문제 → 주거용 프록시 필요
  _abck 마커 '~-1~' → 센서 검증 실패 (브라우저가 봇으로 감지됨)
                      → 브라우저 환경(WebGL/폰트/헤드리스 흔적) 문제
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ssg_crawler import SSGCrawler

MAIN = SSGCrawler.WARMUP_MAIN_URL
ITEM = SSGCrawler.WARMUP_ITEM_URL


def _abck_state(cookies):
    for c in cookies:
        if c["name"] == "_abck":
            parts = c["value"].split("~")
            marker = parts[1] if len(parts) > 1 else "?"
            return marker, c["value"][:40]
    return None, None


def probe(page):
    print(f"DISPLAY={os.environ.get('DISPLAY', '(없음)')}")

    page.goto(MAIN)
    page.wait_for_timeout(3000)
    print(f"메인: title={page.title()[:30]!r}, HTML={len(page.content())}B")

    # 브라우저 환경 지문
    env = page.evaluate(
        """() => {
            const c = document.createElement('canvas');
            const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
            let vendor = 'none', renderer = 'none';
            if (gl) {
                const d = gl.getExtension('WEBGL_debug_renderer_info');
                if (d) {
                    vendor = gl.getParameter(d.UNMASKED_VENDOR_WEBGL);
                    renderer = gl.getParameter(d.UNMASKED_RENDERER_WEBGL);
                }
            }
            return {
                webdriver: navigator.webdriver,
                ua: navigator.userAgent,
                langs: navigator.languages.join(','),
                screen: screen.width + 'x' + screen.height,
                hw: navigator.hardwareConcurrency,
                webglVendor: vendor,
                webglRenderer: renderer,
            };
        }"""
    )
    for k, v in env.items():
        print(f"  {k}: {str(v)[:70]}")

    # 사람 흔적 공급 후 센서 POST 시간을 넉넉히 준다
    for x, y in ((200, 300), (400, 350), (600, 500), (350, 650)):
        page.mouse.move(x, y)
        page.wait_for_timeout(400)
    page.mouse.wheel(0, 700)
    page.wait_for_timeout(3000)
    page.mouse.wheel(0, -300)
    page.wait_for_timeout(4000)

    marker, head = _abck_state(page.context.cookies())
    print(f"\n_abck 마커: {marker}  (값 앞부분: {head})")

    for attempt in (1, 2):
        page.goto(ITEM)
        page.wait_for_timeout(3000)
        html = page.content()
        has_price = "ssg_price" in html
        print(f"상품 시도{attempt}: HTML={len(html)}B, 가격={has_price}")
        if has_price:
            break
        marker2, _ = _abck_state(page.context.cookies())
        print(f"  → 실패, _abck 마커={marker2}, 8초 대기 후 재시도")
        page.wait_for_timeout(8000)

    print("\n--- 판정 ---")
    marker3, _ = _abck_state(page.context.cookies())
    if "ssg_price" in page.content():
        print("✅ 브라우저 워밍업 성공 — 크롤러가 동작해야 정상")
    elif marker3 == "0":
        print("⛔ 센서는 통과했으나 상품 403 → IP 평판 문제 (주거용 프록시 필요)")
    else:
        print("⛔ 센서 검증 실패 → 브라우저가 봇으로 감지됨 (환경 지문 문제)")
    return page


def main():
    SSGCrawler._ensure_virtual_display()
    from scrapling.fetchers import StealthySession

    session = StealthySession(headless=False, timeout=60000, retries=1)
    session.start()
    try:
        session.fetch(MAIN, page_action=probe)
    finally:
        session.close()


if __name__ == "__main__":
    main()
