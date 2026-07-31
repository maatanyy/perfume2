"""SSG 차단 상태 진단 CLI.

사용법:
    venv/bin/python scripts/diag_ssg.py

메인 페이지/상품 페이지를 curl_cffi(chrome 위장)로 1회씩 요청해
현재 IP의 차단 상태를 판정한다. 실행 전 SSG 크롤링 잡이 돌고 있지
않아야 정확하다 (잡의 요청이 차단을 계속 갱신함).
"""

import sys

from curl_cffi import requests as cr

ITEM_URL = "https://shinsegaemall.ssg.com/item/itemView.ssg?itemId=1000860342112"
MAIN_URL = "https://shinsegaemall.ssg.com/"


def main():
    try:
        m = cr.get(MAIN_URL, impersonate="chrome", timeout=15)
        print(f"메인 페이지: HTTP {m.status_code}")
    except Exception as e:
        print(f"메인 페이지: 요청 실패 ({e})")
        sys.exit(1)

    try:
        r = cr.get(
            ITEM_URL,
            impersonate="chrome",
            timeout=15,
            headers={"Accept-Language": "ko-KR,ko;q=0.9"},
        )
        print(f"상품 페이지: HTTP {r.status_code} (HTML {len(r.text)}바이트)")
    except Exception as e:
        print(f"상품 페이지: 요청 실패 ({e})")
        sys.exit(1)

    if r.status_code == 200 and len(r.text) > 100_000:
        print("\n판정: ✅ 차단 해제됨 — SSG 크롤링 재시도 가능")
    elif r.status_code == 403 and m.status_code == 200:
        print("\n판정: ⛔ 상품 페이지만 차단 중 (IP 차단 지속) — 더 기다린 뒤 재실행")
    else:
        print("\n판정: ⛔ 전면 차단 중 — 더 기다린 뒤 재실행")


if __name__ == "__main__":
    main()
