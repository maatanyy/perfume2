# 크롤링 웹 애플리케이션

구글 시트 기반 다중 사이트 크롤링 웹 애플리케이션

## 설치 및 실행

### 1. 가상환경 생성 및 활성화

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

### 2. 의존성 설치

```bash
pip install -r requirements.txt
```

### 3. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 편집하여 필요한 값 설정
```

### 4. 데이터베이스 초기화

```bash
python
>>> from app import create_app, db
>>> app = create_app()
>>> with app.app_context():
...     db.create_all()
...     exit()
```

### 5. 관리자 계정 생성

```bash
python create_admin.py
```

### 6. 애플리케이션 실행

```bash
python app.py
```

브라우저에서 `http://localhost:5000` 접속

## 주요 기능

- 회원가입/로그인 (관리자 승인 필요)
- 구글 시트 연동
- 다중 사이트 동시 크롤링
  - SSG
  - CJ 온스타일
  - 신세계 쇼핑
  - 롯데 아이몰
  - GS Shop
- 실시간 진행률 표시
- 작업 취소 기능
- 관리자 대시보드
- URL 기반 자동 크롤러 선택

## 프로젝트 구조

```
perfume2/
├── app.py                 # Flask 앱 메인
├── config.py              # 설정 파일
├── models/                # 데이터베이스 모델
├── routes/                # 라우트 (auth, dashboard, admin, api)
├── crawlers/              # 크롤러 모듈
├── utils/                 # 유틸리티
├── templates/             # Jinja2 템플릿
└── static/                # 정적 파일
```

## 참고

- 기존 Chrome Extension 코드를 참고하여 Python으로 변환
- Threading 방식으로 크롤링 작업 실행
- 향후 Celery + Redis로 전환 가능

