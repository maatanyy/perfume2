# 🚀 시작하기 (중요!)

## ⚠️ 반드시 이 순서대로 실행하세요!

### 1단계: 가상환경 활성화
```bash
cd /Users/nohminsung/Desktop/perfume2
source venv/bin/activate
```

### 2단계: 데이터베이스 초기화 (처음 한 번만)
```bash
python init_db.py
```

이 단계를 건너뛰면 `RuntimeError`가 발생합니다!

### 3단계: 관리자 계정 생성 (처음 한 번만)
```bash
python create_admin.py
```

이메일과 비밀번호를 입력하세요.

### 4단계: 웹 서버 실행
```bash
python app.py
```

이제 브라우저에서 `http://localhost:5000` 접속 가능합니다.

---

## ❌ 오류가 발생하는 경우

### "RuntimeError: The current Flask app is not registered..."

**원인:** 데이터베이스가 초기화되지 않았습니다.

**해결:**
```bash
# 1. 가상환경 활성화
source venv/bin/activate

# 2. 데이터베이스 초기화 (반드시 먼저 실행!)
python init_db.py

# 3. 그 다음 서버 실행
python app.py
```

---

## ✅ 올바른 실행 순서

```bash
# 터미널 1: 가상환경 활성화 및 초기화
cd /Users/nohminsung/Desktop/perfume2
source venv/bin/activate
python init_db.py          # ← 이게 중요!
python create_admin.py     # ← 이것도 중요!

# 터미널 2: 서버 실행
cd /Users/nohminsung/Desktop/perfume2
source venv/bin/activate
python app.py
```

---

## 🔍 문제 진단

데이터베이스 파일이 있는지 확인:
```bash
ls -la crawling.db
```

파일이 없으면:
```bash
python init_db.py
```

---

## 💡 핵심 정리

1. **반드시** `python init_db.py`를 먼저 실행해야 합니다
2. **그 다음** `python create_admin.py`로 관리자 계정을 만듭니다
3. **마지막으로** `python app.py`로 서버를 실행합니다

이 순서를 지키지 않으면 `RuntimeError`가 발생합니다!

