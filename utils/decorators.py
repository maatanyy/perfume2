from functools import wraps
from flask import abort, redirect, url_for
from flask_login import current_user

def admin_required(f):
    """관리자 권한 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def approved_required(f):
    """승인된 사용자만 접근 가능한 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_approved:
            return redirect(url_for('auth.pending'))
        return f(*args, **kwargs)
    return decorated_function

