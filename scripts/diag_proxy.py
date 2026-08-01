"""프록시 연결/고정 여부 진단.

사용법:
    venv/bin/python scripts/diag_proxy.py

.env의 SSG_PROXY로 IP 조회 서비스에 5번 요청해 다음을 확인한다:
  - 프록시 연결 자체가 되는지
  - 나가는 IP가 한국인지
  - 요청 간 IP가 고정(sticky)되는지  ← 센서 쿠키 유지에 필수
"""

import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from crawlers.ssg_crawler import SSGCrawler  # noqa: E402


def _mask(proxy: str) -> str:
    """비밀번호를 가린 표시용 문자열."""
    if "@" not in proxy:
        return proxy
    creds, host = proxy.rsplit("@", 1)
    scheme, _, userinfo = creds.partition("://")
    user = userinfo.split(":", 1)[0]
    return f"{scheme}://{user}:****@{host}"


def _lookup_country(session, ip: str) -> str:
    """국가 코드 조회. 조회 서비스가 봇 차단 페이지를 반환하는 경우가 있어
    (ipapi.co의 Cloudflare 챌린지 등) 두 곳을 시도하고, 2글자 국가 코드가
    아니면 '?'로 처리한다 — HTML 덩어리를 그대로 출력하지 않기 위함."""
    for url, extract in (
        ("http://ip-api.com/json/{ip}", lambda r: r.json().get("countryCode")),
        ("https://ipinfo.io/{ip}/country", lambda r: r.text.strip()),
    ):
        try:
            value = extract(session.get(url.format(ip=ip), timeout=15))
        except Exception:
            continue
        if value and len(value) == 2 and value.isalpha():
            return value.upper()
    return "?"


def main():
    proxy = SSGCrawler._proxy()
    if not proxy:
        print("⛔ SSG_PROXY가 설정되지 않았습니다 (.env 확인 필요)")
        sys.exit(1)
    print(f"프록시: {_mask(proxy)}\n")

    from curl_cffi import requests as cr

    session = cr.Session(impersonate="chrome", proxies={"http": proxy, "https": proxy})
    ips = []
    for i in range(5):
        try:
            r = session.get("https://api.ipify.org?format=json", timeout=20)
            ip = r.json().get("ip")
            ips.append(ip)
            print(f"요청 {i + 1}: {ip}")
        except Exception as e:
            print(f"요청 {i + 1}: ⛔ 연결 실패 — {str(e)[:100]}")
            print("\n→ 아이디/비번/호스트/포트를 다시 확인하세요")
            sys.exit(1)
        time.sleep(3)

    print()
    geo = _lookup_country(session, ips[-1])
    print(f"IP 국가: {geo}")

    unique = len(set(ips))
    if unique == 1:
        print("IP 고정: ✅ 5회 모두 동일 (sticky 정상)")
    else:
        print(f"IP 고정: ⚠️ {unique}종류로 바뀜 — sticky 포트(10000~20000)인지 확인 필요")

    if unique > 1:
        print("\n판정: ⚠️ IP가 회전 중 — 포트를 10000으로 바꾸면 대개 해결됩니다")
    elif geo == "KR":
        print("\n판정: ✅ 프록시 정상 — diag_ssg.py로 SSG 접근을 확인하세요")
    elif geo == "?":
        print("\n판정: ✅ 연결·고정은 정상 (국가 조회는 실패 — 무시 가능)")
        print("   diag_ssg.py로 SSG 접근을 확인하세요")
    else:
        print(f"\n판정: ⚠️ 한국 IP가 아님({geo}) — 대시보드에서 국가를 South Korea로 지정하세요")


if __name__ == "__main__":
    main()
