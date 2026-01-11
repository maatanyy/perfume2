"""데이터베이스 초기화 스크립트"""
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def init_database():
    """데이터베이스 초기화"""
    from app import create_app
    
    app = create_app()
    
    # app.app_context() 내에서 db import
    with app.app_context():
        from app import db
        from models.user import User
        from models.crawling_job import CrawlingJob
        from models.crawling_log import CrawlingLog
        
        print("데이터베이스 초기화 중...")
        try:
            db.create_all()
            print("✅ 데이터베이스 초기화 완료!")
            print("다음 단계: python create_admin.py 로 관리자 계정을 생성하세요.")
        except Exception as e:
            print(f"❌ 오류 발생: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    init_database()
