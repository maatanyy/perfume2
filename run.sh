#!/bin/bash
# 실행 스크립트

echo "🚀 크롤링 웹 애플리케이션 실행 스크립트"
echo ""

# 가상환경 확인
if [ ! -d "venv" ]; then
    echo "❌ 가상환경이 없습니다. 먼저 다음 명령어를 실행하세요:"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# 가상환경 활성화
source venv/bin/activate

# 데이터베이스 확인
if [ ! -f "crawling.db" ]; then
    echo "📦 데이터베이스가 없습니다. 초기화 중..."
    python init_db.py
    echo ""
    echo "⚠️  관리자 계정을 생성하세요:"
    echo "   python create_admin.py"
    echo ""
    read -p "계속하시겠습니까? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# .env 파일 확인
if [ ! -f ".env" ]; then
    echo "📝 .env 파일이 없습니다. .env.example을 복사합니다..."
    cp .env.example .env
    echo "✅ .env 파일이 생성되었습니다. 필요시 수정하세요."
    echo ""
fi

# Flask 앱 실행
echo "🌟 Flask 애플리케이션 시작 중..."
echo "   브라우저에서 http://localhost:5000 접속하세요"
echo "   종료하려면 Ctrl+C를 누르세요"
echo ""
python app.py

