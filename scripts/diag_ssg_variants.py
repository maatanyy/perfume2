"""SSG 워밍업 변형 실험 — 서버에서 센서를 통과하는 브라우저 설정을 찾는다.

사용법:
    venv/bin/python scripts/diag_ssg_variants.py

각 변형마다 브라우저를 새로 띄워 메인 방문 → 상호작용 → 상품 페이지를
시도한다. 성공한 변형이 있으면 크롤러에 반영하면 되고, 전부 실패하면
브라우저 설정으로는 해결 불가(= IP 평판 문제)라는 뜻이다.

주의: JS 주입(init_script/add_init_script)은 patchright가 봇 탐지 벡터로
차단해 무효다 (2026-08-01 실측) — 실제로 적용되는 옵션만 시험한다.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ssg_crawler import SSGCrawler

MAIN = SSGCrawler.WARMUP_MAIN_URL
ITEM = SSGCrawler.WARMUP_ITEM_URL

WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

VARIANTS = [
    ("1. 기준 (현재 설정)", {}),
    ("2. 한국 로케일", {"locale": "ko-KR"}),
    ("3. 윈도우 UA + 한국 로케일", {"useragent": WINDOWS_UA, "locale": "ko-KR"}),
    (
        "4. 윈도우 UA + 한국 로케일 + GPU 플래그",
        {
            "useragent": WINDOWS_UA,
            "locale": "ko-KR",
            "extra_flags": ["--use-gl=angle", "--use-angle=gl-egl"],
        },
    ),
    ("5. 실제 Chrome 사용 (설치되어 있어야 함)", {"locale": "ko-KR", "real_chrome": True}),
]


def _browse(page, holder):
    page.goto(MAIN)
    page.wait_for_timeout(3000)
    for x, y in ((200, 300), (400, 350), (600, 500), (350, 650)):
        page.mouse.move(x, y)
        page.wait_for_timeout(400)
    page.mouse.wheel(0, 700)
    page.wait_for_timeout(3000)
    page.mouse.wheel(0, -300)
    page.wait_for_timeout(3000)
    page.goto(ITEM)
    page.wait_for_timeout(4000)
    holder["html"] = page.content()
    return page


def run(label, options):
    from scrapling.fetchers import StealthySession

    session = None
    try:
        session = StealthySession(headless=False, timeout=60000, retries=1, **options)
        session.start()
        holder = {}
        session.fetch(MAIN, page_action=lambda page: _browse(page, holder))
        html = holder.get("html", "")
        ok = "ssg_price" in html
        print(f"{label}: {'✅ 성공' if ok else '❌ 실패'} (HTML {len(html):,}B)")
        return ok
    except Exception as e:
        print(f"{label}: ⚠️ 실행 불가 — {str(e)[:90]}")
        return False
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def main():
    SSGCrawler._ensure_virtual_display()
    for label, options in VARIANTS:
        if run(label, options):
            print(f"\n→ 이 설정을 크롤러에 반영하면 됩니다: {label}")
            print(f"   옵션: {options}")
            return
    print("\n→ 모든 변형 실패 = 브라우저 설정 문제가 아님 (서버 IP 평판 문제)")
    print("   해결책: 주거용 프록시 경유 또는 다른 네트워크에서 실행")


if __name__ == "__main__":
    main()
