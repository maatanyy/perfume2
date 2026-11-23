# 인수인계: 리눅스 서버 → 집 윈도우 PC 이전 (2026-11-23)

## 현재 상황
- **운영 서버(아직 가동 중, 폐기 예정)**: 2vCPU / RAM 3.8GB(+스왑 4GB) / SSD 50GB, (접속 정보는 문서에 적지 않음 — 사용자에게 확인)
  - systemd 서비스 `perfume3` = `gunicorn --workers 1 --worker-class gthread --threads 4 --bind 0.0.0.0:5001`
  - 경로 `/root/perfume3`, venv `venv/`, 배포는 `git fetch origin && git reset --hard origin/main` → `systemctl restart perfume3`
  - apt 사용 시 `NEEDRESTART_SUSPEND=1` 프리픽스 필요
- **목표**: 집의 고사양 윈도우 데스크톱(24시간 켜둠)으로 대체. 회사(한국)에서 동료 2~3명이 접속.
- **비용 목표**: 무료.

## 이번에 끝낸 작업 (브랜치 `windows-migration`, main에는 아직 미반영)
1. URL 라우팅 중복 제거 — `crawlers/crawler_factory.py`가 단일 출처. 엔진/재시도 패스/대시보드 모두 사용.
   (과거 결과 파일 URL 2만여 건의 호스트가 전부 5개 도메인 안 → 동작 변화 없음 확인)
2. 미사용 코드 삭제 — Selenium/undetected-chromedriver 경로, `utils/browser_pool.py`, `utils/retry_handler.py`,
   `config/sites_config.json`, `test_http.py`, 브라우저 풀 API·모니터링 UI, 미사용 패키지(requirements).
3. 설정 이중화 해소 — 동시 잡 상한/워커 수/메모리 임계값을 `config.py`(환경변수)에서만 읽음.
   메모리 임계값 기본값은 실제 적용되던 2500/3200MB.
4. CJ 주석 정정 — 실제 브라우저는 patchright Chromium.
- 검증: pytest 142개 통과, 임시 DB로 주요 화면/API 200 확인, 신세계 실URL 수집 성공.

## 결정된 방향
- **네이티브 윈도우 + waitress** (gunicorn은 윈도우 미지원. waitress는 1프로세스·멀티스레드라 앱 구조와 맞음 —
  엔진이 프로세스 안 백그라운드 스레드로 돌기 때문에 **반드시 프로세스 1개**).
- **외부 공개는 Tailscale Funnel (무료, 고정 주소 `https://<기기명>.<tailnet>.ts.net`)** 이 1순위.
  나중에 깔끔한 주소가 필요하면 Cloudflare Tunnel + 유료 도메인(연 1~2만원)으로 이전 가능 — 앱은 그대로.
  비추천: trycloudflare(주소 매번 바뀜), ngrok 무료(경고 페이지), 포트포워딩(IP 노출·HTTPS 수작업).
- SSG Camoufox 워밍업은 headless라 윈도우에서 Xvfb 불필요 (`_ensure_virtual_display`가 Linux에서만 동작).

## 성능 기대치 (중요)
고사양이어도 **대부분 빨라지지 않는다.** 병목은 CPU가 아니라 차단 회피용 요청 간격:
SSG 2~3초 직렬(882건 ≈ 45분), 롯데 1.2초, 신세계 0.3초~. 개선되는 것은 CJ(브라우저 렌더링)와
5개 사이트 동시 실행 시 안정성(메모리 부족/스왑/좀비 브라우저 해소) 정도.
집 IP로 크롤링하므로 사이트에 차단되면 **집의 일반 쇼핑 접속도 막힐 수 있다** → 간격 축소 금지.

## 다음 할 일 (순서대로)
1. [ ] **실제 IP 인식 수정** — 터널 뒤에서는 모든 요청이 127.0.0.1로 보여 Flask-Limiter 한도
   (기본 200/일, 50/시간)를 전원이 나눠 쓰게 됨. `X-Forwarded-For`를 신뢰하도록(예: werkzeug `ProxyFix`, x_for=1) 수정.
2. [ ] 윈도우용 `start.bat` 작성 (프로젝트 폴더에서 `venv\Scripts\waitress-serve --listen=127.0.0.1:5001 --threads=8 wsgi:app`).
   127.0.0.1에만 바인드 — 외부 노출은 터널만 담당.
3. [ ] 윈도우 PC 세팅
   - Python 3.12, Git 설치 → clone → `git checkout windows-migration`
   - `py -3.12 -m venv venv` → `venv\Scripts\pip install -r requirements.txt waitress`
   - `venv\Scripts\scrapling install`, `venv\Scripts\python -m camoufox fetch`
   - `pytest -q`로 확인
4. [ ] 데이터 이전 — 서버에서 `systemctl stop perfume3` 후 `crawling.db`(+`-wal`/`-shm`)와 `.env`를 PC로 복사
   (예: `scp <서버>:/root/perfume3/crawling.db .`). `results/`는 선택.
   `.env`: `FLASK_ENV=production`, **서버의 `SECRET_KEY` 그대로 유지**(없으면 재시작마다 전원 로그아웃).
   `SSG_PROXY`는 집 주거용 IP라 불필요할 가능성 높음(원인은 IP가 아니라 지문이었음).
   ※ 이전 확인 전까지 서버는 다시 켜둬도 됨(`systemctl start perfume3`) — 단 이후 생긴 데이터는 다시 옮겨야 함.
5. [ ] Tailscale 설치·로그인 → `tailscale funnel --bg 5001` → 동료 접속 테스트.
6. [ ] 자동 시작 — 작업 스케줄러 "시스템 시작 시, 로그온 여부와 관계없이"로 `start.bat` 등록.
   절전 끄기, Windows 업데이트 사용 시간 설정, BIOS "AC 전원 복구 시 켜기".
7. [ ] 1~2주 병행/검증 후 `windows-migration` → main 병합, 서버 폐기.

## 윈도우 관련 주의
- `CrawlingEngineV2._kill_browser_processes`는 `signal.SIGKILL`이 윈도우에 없어 조용히 실패(무동작)한다.
  **이게 맞다** — 동작하면 사용자가 쓰는 개인 Chrome까지 전부 죽인다. 윈도우에서 "고치지" 말 것.
- 집 PC는 개인 데이터가 있는 기기다. 앱은 로그인+관리자 승인 구조이지만, 공개 범위는 터널 하나로 한정할 것.

## 과거 이력 요약 (SSG 차단)
2026-07-31부터 SSG(Akamai) 403. "IP 차단"·"데이터센터 IP 평판" 두 번 오판 후 확정한 원인은
**서버 브라우저 지문**(GPU 없음 → WebGL llvmpipe). Camoufox(os=windows, 내장 DB에 있는 WebGL 조합 GTX 980)
워밍업 + HTTP는 `impersonate="firefox"`로 해결(커밋 b30d830). Camoufox `humanize=True`는 headless에서 무한 대기 → False.
