# -*- coding: utf-8 -*-
"""
权限校验 + Token 验证
"""
from functools import wraps
from flask import g, request, jsonify
from core.response import error_response


def require_permission(perm_code):
    """操作权限校验装饰器（全局共享）"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = getattr(g, 'current_user', None)
            if user and user.role:
                perms = user.role.permissions_list()
                if perm_code in perms:
                    return f(*args, **kwargs)
            return error_response('无操作权限', 403)
        return wrapper
    return decorator


def require_any_permission(*perm_codes):
    """操作权限校验装饰器：传入多个权限码，任一匹配即可通过（用于跨模块复用的接口）"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = getattr(g, 'current_user', None)
            if user and user.role:
                perms = user.role.permissions_list()
                if any(p in perms for p in perm_codes):
                    return f(*args, **kwargs)
            return error_response('无操作权限', 403)
        return wrapper
    return decorator


# ============================================================
# Token 验证工具
# ============================================================

def _get_token_from_request(req):
    """从 Authorization 请求头或 query 参数提取 Token"""
    auth_header = req.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    # EventSource 等无法设置自定义 Header，允许通过 query 参数传递
    return req.args.get('token') or None


def validate_token(req):
    """
    验证请求中的 Token，返回 User 快照或 None。

    - 第一步：Redis 会话快照校验（token 有效性与滑动续期）
    - 第二步：每次请求原子校验——实时查 DB 用户是否存在/是否被禁用/角色权限是否变化；
      禁用（平台自禁或认证中心同步后）即时拦截，角色变更即时生效，均无需重新登录。
    Redis 不可用时返回 None（按未登录处理），由前端引导重新登录。
    供 app.py 的 before_request 调用
    """
    token_str = _get_token_from_request(req)
    if not token_str:
        return None

    from modules.system.session_cache import get_session_user, refresh_session
    user = get_session_user(token_str)
    if user is None:
        return None

    # 实时原子校验（内网规模每次请求一次单行查询，代价可接受）
    from sqlalchemy.orm import joinedload
    from modules.system.models import User
    db_user = User.query.options(joinedload(User.role)).filter_by(id=user.id).first()
    if db_user is None or not db_user.is_active:
        # 用户不存在或被禁用（平台自禁 / 认证中心同步禁用）→ 按未登录处理
        return None
    # 实时角色/权限覆盖快照：角色升降权即时生效
    user.apply_real_time(db_user)

    # 滑动过期：有效请求重置会话 TTL（失败不影响本次鉴权）
    refresh_session(token_str)
    return user


# ============================================================
# 全局鉴权钩子
# ============================================================

# 白名单：无需 Token 即可访问的 API 路径
AUTH_WHITELIST = [
    '/api/auth/login',
    '/api/auth/admin-login',
]
# 白名单前缀
AUTH_WHITELIST_PREFIXES = [
    '/health',
    '/api/cicd/agent/',
]


def init_auth(app):
    """注册全局 before_request 鉴权钩子"""

    @app.before_request
    def check_auth():
        # 静态文件、页面路由不拦截
        if request.endpoint == 'static' or not request.path.startswith('/api/'):
            return None

        # 白名单放行
        if request.path in AUTH_WHITELIST:
            return None
        for prefix in AUTH_WHITELIST_PREFIXES:
            if request.path.startswith(prefix):
                return None

        # Token 验证
        user = validate_token(request)
        if user is None:
            return jsonify({'code': 401, 'msg': '未登录或Token已过期', 'data': None}), 401

        # 将用户对象存入 g，供后续接口使用
        g.current_user = user
        return None
