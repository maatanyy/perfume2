# perfume3 — 향수 가격 조사 크롤러 (Flask)

구글 시트(공개 CSV)의 상품 URL을 읽어 SSG·CJ온스타일·신세계TV쇼핑·롯데아이몰·GS샵 가격을
수집하고 엑셀(`results/`)로 저장하는 사내용 웹앱. 회사 동료 2~3명이 외부에서 접속해 사용한다.

**진행 중인 작업과 다음 할 일은 `docs/handoff/2026-11-23-windows-migration.md`를 먼저 읽을 것.**

## 절대 규칙
- `crawling.db`는 실사용자 데이터(가입 유저/잡/로그). 삭제·재생성·스키마 변경 금지. git untracked.
  옮길 때는 앱을 멈춘 뒤 `crawling.db`(+ `-wal`, `-shm`)를 함께 복사한다.
- `python app.py`(debug=True, 0.0.0.0)로 외부 공개 금지 — Werkzeug 디버거 = 원격 코드 실행.
  운영은 WSGI 서버(`wsgi:app`)로만 띄운다.
- 사이트별 요청 간격/냉각/서킷 브레이커 값은 실측으로 정한 것(코드 주석에 근거·날짜 있음).
  속도를 위해 함부로 줄이지 말 것 — 차단되면 운영 IP 전체가 막힌다.

## 구조
- `app.py`(팩토리, `.env` 로드) / `wsgi.py`(운영 진입점, 좀비 잡 정리) / `config.py`(모든 설정, 환경변수로 덮어씀)
- `routes/` dashboard·api(SSE 진행률)·admin·auth
- `utils/crawling_engine_v2.py` 잡 실행(배치+스레드풀, 결과 4분류 success/sold_out/not_found/error, 잡 말미 오류 재시도)
- `crawlers/crawler_factory.py` 사이트 키/URL → 크롤러 라우팅의 **단일 출처** (`SITES`, `DOMAIN_CRAWLERS`)
- `crawlers/*_crawler.py` 사이트별. 전부 HTTP 기반이고 브라우저가 필요한 곳만 자체 처리:
  - SSG: Camoufox 워밍업으로 Akamai 센서 쿠키 확보 → curl_cffi(firefox 위장) HTTP. 간격 2~3초 직렬.
  - CJ: scrapling StealthySession(**patchright Chromium**, Camoufox 아님) 1개를 전용 스레드에 고정.
  - 롯데: 메인 방문 쿠키 + 간격 1.2초 / 신세계TV: 적응형 간격 0.3초~ / GS: 일반 HTTP.
- `utils/excel_report.py` 결과 엑셀, `utils/memory_monitor.py` RSS 모니터.

## 개발
- 테스트: `pytest -q` (네트워크 없이 동작, 142개)
- 단건 실검증: `python scripts/verify_crawler.py '<상품URL>'`
- 설치 후 1회: `scrapling install`, `python -m camoufox fetch`
- 커밋 메시지는 한국어 `type: 요약` 형식 (기존 로그 참고).
