# 🚀 크롤링 시스템 개선 완료

## 📋 개선 요약

### 주요 변경사항

| 항목 | 이전 | 개선 후 |
|------|------|---------|
| **동시 작업 수** | 5개 | **10개** |
| **브라우저 관리** | 매번 새로 생성 | **브라우저 풀 (재사용)** |
| **메모리 관리** | 수동 GC | **자동 모니터링 + 경고** |
| **에러 핸들링** | 단순 try-catch | **재시도 데코레이터 + 서킷 브레이커** |
| **리소스 정리** | 불완전 | **Context Manager + 자동 정리** |

---

## 📁 새로 추가된 파일

### 1. 브라우저 풀 매니저
**파일**: `utils/browser_pool.py`

```
특징:
- 최대 2개 브라우저 인스턴스 관리
- 30회 요청 후 자동 재활용 (메모리 누수 방지)
- 5분 후 자동 종료
- Context Manager 지원으로 안전한 리소스 정리
```

### 2. 메모리 모니터링
**파일**: `utils/memory_monitor.py`

```
특징:
- 5초마다 메모리 사용량 체크
- 2.5GB 경고 / 3.2GB 위험 임계치
- 자동 가비지 컬렉션
- 위험 상황 시 콜백 실행 (브라우저 풀 리셋)
```

### 3. 재시도 유틸리티
**파일**: `utils/retry_handler.py`

```python
# 사용 예시
@retry(max_attempts=3, delay=2, backoff=1.5)
def crawl_with_retry(url):
    return fetch_data(url)
```

### 4. 하이브리드 크롤러
**파일**: `crawlers/hybrid_crawler.py`

```
전략:
1. HTTP 요청 우선 시도 (빠르고 가벼움)
2. 실패하거나 JS 렌더링 필요 시 브라우저 사용
3. 사이트별 최적 방식 자동 선택
```

### 5. 개선된 크롤링 엔진 v2
**파일**: `utils/crawling_engine_v2.py`

```
개선사항:
- 브라우저 풀 통합
- 메모리 모니터링 통합
- 세마포어 기반 동시성 제어
- 상세 작업 통계 제공
```

### 6. 사이트 설정 파일
**파일**: `config/sites_config.json`

```json
{
  "sites": {
    "ssg.com": {
      "requires_javascript": true,
      "wait_time": 5,
      "retry_count": 3
    },
    "gsshop.com": {
      "requires_javascript": false,
      "wait_time": 2
    }
  }
}
```

### 7. 모니터링 대시보드
**파일**: `templates/admin/monitoring.html`
**URL**: `/admin/monitoring`

```
기능:
- 실시간 메모리 사용량 표시
- 브라우저 풀 상태 표시
- 활성 작업 목록
- 수동 GC 실행 버튼
- 브라우저 풀 리셋 버튼
```

---

## 🔧 수정된 파일

1. **app.py**
   - 로깅 설정 추가
   - 크롤링 엔진 v2 초기화
   - 앱 종료 시 리소스 정리 등록

2. **config.py**
   - 브라우저 풀 설정 추가
   - 메모리 임계치 설정 추가
   - 동시 작업 수 10개로 증가

3. **routes/dashboard.py**
   - 새 크롤링 엔진 v2 사용
   - 동시 작업 제한 10개로 증가

4. **routes/admin.py**
   - 모니터링 페이지 라우트 추가

5. **routes/api.py**
   - 시스템 상태 API 추가
   - 메모리 상태 API 추가
   - 브라우저 풀 상태 API 추가
   - 강제 GC API 추가
   - 브라우저 풀 리셋 API 추가

---

## 📊 새 API 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/api/system/status` | GET | 시스템 전체 상태 |
| `/api/system/memory` | GET | 메모리 상세 정보 |
| `/api/system/memory/gc` | POST | 강제 GC 실행 (관리자) |
| `/api/system/browser-pool` | GET | 브라우저 풀 상태 |
| `/api/system/browser-pool/reset` | POST | 풀 리셋 (관리자) |
| `/api/jobs/<id>/stats` | GET | 작업 상세 통계 |
| `/api/jobs/<id>/logs` | GET | 작업 로그 목록 |

---

## 🎯 성능 목표 달성

### 달성 항목
- ✅ **동시 작업 5~10개**: 10개로 설정
- ✅ **메모리 안정화**: 자동 모니터링 + GC
- ✅ **브라우저 자동 정리**: 풀 기반 관리
- ✅ **에러 핸들링**: 재시도 + 서킷 브레이커
- ✅ **실시간 모니터링**: 관리자 대시보드

### 환경 설정 (4GB RAM, 2 vCPU)

| 설정 | 값 | 설명 |
|------|-----|------|
| `MAX_TOTAL_CONCURRENT_JOBS` | 10 | 시스템 최대 동시 작업 |
| `BROWSER_POOL_MAX_BROWSERS` | 2 | 최대 브라우저 수 |
| `BROWSER_POOL_MAX_REQUESTS` | 30 | 재활용 전 최대 요청 |
| `MEMORY_WARNING_THRESHOLD_MB` | 2500 | 경고 임계치 |
| `MEMORY_CRITICAL_THRESHOLD_MB` | 3200 | 위험 임계치 |

---

## 🚀 사용 방법

### 1. 서버 시작
```bash
cd /Users/nohminsung/Desktop/perfume2
source per/bin/activate
python app.py
```

### 2. 접속
- **메인**: http://localhost:5001
- **모니터링**: http://localhost:5001/admin/monitoring

### 3. 시스템 상태 확인
```bash
curl http://localhost:5001/api/system/status
```

---

## 🔍 트러블슈팅

### 메모리 사용량이 높을 때
1. 모니터링 페이지에서 "GC 실행" 클릭
2. 필요 시 "브라우저 풀 리셋" 클릭

### 크롤링이 느릴 때
1. `CRAWLING_MAX_WORKERS` 값 조정 (기본 2)
2. `CRAWLING_BATCH_SIZE` 값 조정 (기본 10)

### 브라우저 에러 발생 시
1. 브라우저 풀 리셋 실행
2. Chrome 드라이버 버전 확인
3. 시스템 재시작

---

## 📝 환경 변수 (.env)

```bash
# 크롤링 성능
CRAWLING_BATCH_SIZE=10
CRAWLING_MAX_WORKERS=2

# 브라우저 풀
BROWSER_POOL_MAX_BROWSERS=2
BROWSER_POOL_MAX_REQUESTS=30
BROWSER_POOL_MAX_AGE_SECONDS=300

# 메모리 임계치
MEMORY_WARNING_THRESHOLD_MB=2500
MEMORY_CRITICAL_THRESHOLD_MB=3200

# 동시 작업
MAX_CONCURRENT_JOBS_SYSTEM=10
MAX_CONCURRENT_JOBS_PER_USER=5
```

---

## 🏗️ 향후 개선 방향

1. **비동기 처리**: `asyncio` + `aiohttp`로 HTTP 크롤링 병렬화
2. **Celery 통합**: 분산 작업 큐로 확장성 개선
3. **Playwright 도입**: Selenium보다 빠르고 안정적
4. **캐싱**: 동일 URL 재요청 시 캐시 활용
5. **로그 분석**: 실패 패턴 분석 및 자동 대응
