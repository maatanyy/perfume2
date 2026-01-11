"""관리자 계정 생성 스크립트"""
import sys
import os

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def create_admin():
    """관리자 계정 생성"""
    from app import create_app
    
    app = create_app()
    
    # app.app_context() 내에서 db와 모델 import
    with app.app_context():
        from app import db
        from models.user import User
        
        email = input('관리자 이메일을 입력하세요: ').strip().lower()
        password = input('비밀번호를 입력하세요: ').strip()
        
        if not email or not password:
            print('이메일과 비밀번호를 모두 입력해주세요.')
            sys.exit(1)
        
        try:
            # 기존 사용자 확인
            existing_user = User.query.filter_by(email=email).first()
            if existing_user:
                print(f'{email}은(는) 이미 등록된 사용자입니다.')
                response = input('관리자 권한을 부여하시겠습니까? (y/n): ')
                if response.lower() == 'y':
                    existing_user.is_admin = True
                    existing_user.is_approved = True
                    existing_user.set_password(password)
                    db.session.commit()
                    print(f'✅ {email}에 관리자 권한이 부여되었습니다.')
                else:
                    print('취소되었습니다.')
            else:
                # 새 사용자 생성
                user = User(
                    email=email,
                    is_approved=True,
                    is_admin=True
                )
                user.set_password(password)
                db.session.add(user)
                db.session.commit()
                print(f'✅ 관리자 계정이 생성되었습니다: {email}')
        except Exception as e:
            print(f'❌ 오류 발생: {e}')
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    create_admin()
