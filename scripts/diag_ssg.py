"""SSG 크롤링 진단 CLI (브라우저 쿠키 워밍업 포함).

사용법:
    venv/bin/python scripts/diag_ssg.py

실제 크롤러와 동일한 경로(브라우저 워밍업 → 쿠키 이식 → HTTP 수집)로
상품 3건을 수집해 결과를 출력한다. 서버에서 Xvfb/pyvirtualdisplay 설치
여부까지 함께 검증된다.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

# 앱과 동일하게 .env를 읽어야 SSG_PROXY 설정이 진단에도 반영된다
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from crawlers.ssg_crawler import SSGCrawler  # noqa: E402

ITEM_IDS = ["1000860342112", "1000648733689", "1000682706640"]
URL = "https://www.ssg.com/item/itemView.ssg?itemId={}"


def main():
    crawler = SSGCrawler()
    ok = 0
    for item_id in ITEM_IDS:
        result = crawler.crawl_price(URL.format(item_id))
        status = result["결과 상태"]
        if status == "success":
            ok += 1
            print(
                f"{item_id}: ✅ 판매가 {result['판매가']:,}원 "
                f"배송비 {result['배송비']:,}원"
            )
        else:
            print(f"{item_id}: ❌ {status} — {result.get('에러 발생', '')}")

    print()
    if ok == len(ITEM_IDS):
        print("판정: ✅ 정상 — SSG 크롤링 실행 가능")
    elif ok:
        print(f"판정: ⚠️ 부분 성공 ({ok}/{len(ITEM_IDS)}) — 레이트리밋 가능성, 재실행 권장")
    else:
        print("판정: ⛔ 전부 실패 — 아래 로그의 워밍업 실패 사유 확인 필요")
        sys.exit(1)


if __name__ == "__main__":
    main()
