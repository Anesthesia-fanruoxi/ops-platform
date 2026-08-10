# -*- coding: utf-8 -*-
"""
认证接口处理函数 + 健康检查
"""
import secrets
import datetime
from datetime import timedelta
from flask import request, g, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from core.db import db
from modules.system.models import User
from core.response import success_response, error_response
# 模块级导入：_issue_local_session 与 login/admin_login 共用
from modules.system.session_cache import save_session, delete_user_sessions


def _issue_local_session(user):
    """本地发 token 并写 Redis 会话（沿用现有 session_cache 机制）。
    返回 (token_str, expires_at)；Redis 写入失败返回 None。"""
    token_str = secrets.token_urlsafe(32)
    from modules.system.settings_service import get_setting_int
    expire_hours = get_setting_int('token_expire_hours', 8) or 8
    expires_at = datetime.datetime.now() + timedelta(hours=expire_hours)
    delete_user_sessions(user.id)
    saved = save_session(token_str, user, expires_at, expire_hours * 3600)
    if not saved:
        return None
    return token_str, expires_at


def _authp_error_response(result):
    """把 authPlatform 登录失败结果映射为 HTTP 响应"""
    code = result.get('code')
    msg = result.get('msg') or '登录失败'
    if code == 'must_change_password':
        return error_response(f'{msg}，请先修改密码', 403)
    if code == 'multi_step':
        return error_response(msg, 400)
    if code == 'error':
        return error_response(msg, 503)
    http_map = {
        1001: 401, 1002: 503, 1003: 401, 1004: 403,
        1005: 429, 1006: 403, 1007: 400, 1009: 403,
    }
    return error_response(msg, http_map.get(code, 401))


def login():
    """
    登录接口
    请求体: {"username": "admin", "password": "admin123"}
    返回: token + 用户信息（含权限）

    已接入统一鉴权中心（authPlatform）时：转发凭证校验，成功后把用户映射到本地
    users 表并走本地 Redis 会话（token 由本地生成）；未接入时回退本地账号校验。
    """
    data = request.json or {}
    # 统一转小写：MySQL collation 大小写不敏感，避免 'Admin'/'ADMIN' 变体绕过限流锁定键（auth:fail:{username}）
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if not username or not password:
        return error_response('用户名和密码不能为空', 400)

    # 登录限流（Redis 不可用时自动跳过，不拦截；authPlatform 侧也有账号维度锁定）
    from modules.system.session_cache import (
        is_login_locked, record_login_fail, clear_login_fail, save_session,
        delete_user_sessions,
    )
    if is_login_locked(username):
        return error_response('尝试次数过多，请15分钟后再试', 429)

    # ── 统一鉴权中心（authPlatform）接入：配置了接入参数则优先走平台校验 ──
    from modules.system.auth_platform import verify_login, get_config, get_or_create_sso_user
    authp_cfg = get_config()
    if authp_cfg:
        # 逃生通道：本地原生账号（auth_source='local'，如 admin）始终走本地校验，
        # 保证配置期/鉴权中心故障期间管理员仍可登录调整配置，避免「配置了统一登录却登录不进去」的锁死
        local_user = User.query.filter_by(username=username).first()
        if local_user and local_user.auth_source == 'local':
            if not check_password_hash(local_user.password_hash, password):
                record_login_fail(username)
                return error_response('用户名或密码错误', 401)
            if not local_user.is_active:
                return error_response('账号已被禁用，请联系管理员', 403)
            issued = _issue_local_session(local_user)
            if not issued:
                return error_response('认证服务暂不可用（Redis 异常），请稍后再试', 503)
            token_str, expires_at = issued
            clear_login_fail(username)
            return success_response({
                'token': token_str,
                'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
                'user': local_user.to_dict(include_permissions=True),
            }, '登录成功')

        # sso 用户或本地不存在的账号 → 转发 authPlatform 校验
        result = verify_login(username, password, authp_cfg['platform_id'])
        if result is None:
            return error_response('认证服务配置异常，请联系管理员', 503)
        if not result['ok']:
            record_login_fail(username)
            return _authp_error_response(result)

        # 登录成功：映射本地用户 → 发本地会话
        user = get_or_create_sso_user(result['user'])
        if not user:
            return error_response('登录失败：无法映射用户身份，请联系管理员', 403)
        if not user.is_active:
            return error_response('账号已被禁用，请联系管理员', 403)
        if result.get('must_change_password'):
            return error_response('需先修改密码后才能登录，请联系管理员', 403)
        issued = _issue_local_session(user)
        if not issued:
            return error_response('认证服务暂不可用（Redis 异常），请稍后再试', 503)
        token_str, expires_at = issued
        clear_login_fail(username)
        return success_response({
            'token': token_str,
            'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
            'user': user.to_dict(include_permissions=True),
        }, '登录成功')

    # ── 未接入 authPlatform：走本地账号校验（原逻辑）──
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        record_login_fail(username)
        return error_response('用户名或密码错误', 401)

    if not user.is_active:
        return error_response('账号已被禁用，请联系管理员', 403)

    issued = _issue_local_session(user)
    if not issued:
        return error_response('认证服务暂不可用（Redis 异常），请稍后再试', 503)
    token_str, expires_at = issued
    clear_login_fail(username)

    return success_response({
        'token': token_str,
        'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
        'user': user.to_dict(include_permissions=True),
    }, '登录成功')


def admin_login():
    """
    超级管理员本地登录（登录页「管理员登录」标签）

    仅超级管理员（本地账号且 is_super_admin 标记）可用：
    始终走本地密码校验，不受 authPlatform 配置影响（逃生通道的显式入口）。
    非超级管理员一律拒绝，请使用普通登录（统一鉴权）。
    """
    data = request.json or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')

    if not username or not password:
        return error_response('管理员账号和密码不能为空', 400)

    from modules.system.session_cache import (
        is_login_locked, record_login_fail, clear_login_fail,
    )
    if is_login_locked(username):
        return error_response('尝试次数过多，请15分钟后再试', 429)

    user = User.query.filter_by(username=username).first()
    if not user or not user.is_super_admin:
        # 统一失败响应（不区分超管与否）防用户名枚举；不记计数防被刷锁号（DoS）
        return error_response('账号或密码错误', 401)

    if not check_password_hash(user.password_hash, password):
        record_login_fail(username)
        return error_response('账号或密码错误', 401)

    if not user.is_active:
        return error_response('账号已被禁用，请联系管理员', 403)

    issued = _issue_local_session(user)
    if not issued:
        return error_response('认证服务暂不可用（Redis 异常），请稍后再试', 503)
    token_str, expires_at = issued
    clear_login_fail(username)

    return success_response({
        'token': token_str,
        'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
        'user': user.to_dict(include_permissions=True),
    }, '登录成功')


def logout():
    """登出：删除当前 Token"""
    from core.security import _get_token_from_request
    token_str = _get_token_from_request(request)
    if token_str:
        from modules.system.session_cache import delete_session
        delete_session(token_str)
    return success_response(msg='已退出登录')


def me():
    """获取当前登录用户信息（含权限）"""
    user = getattr(g, 'current_user', None)
    if not user:
        return error_response('未登录', 401)
    return success_response(user.to_dict(include_permissions=True))


def change_password():
    """
    修改密码
    请求体: {"old_password": "...", "new_password": "..."}
    """
    current = getattr(g, 'current_user', None)
    if not current:
        return error_response('未登录', 401)

    # 回源 DB 取 ORM 用户（g.current_user 是 Redis 会话快照，无 password_hash）
    user = User.query.get(current.id)
    if not user:
        return error_response('用户不存在', 404)
    # 统一鉴权账号（sso）本地无密码，改密应走认证中心
    if user.auth_source != 'local':
        return error_response('统一鉴权账号请到认证中心修改密码', 400)

    data = request.json or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '').strip()

    if not old_password or not new_password:
        return error_response('旧密码和新密码不能为空', 400)

    from modules.system.settings_service import check_password_policy
    ok_policy, policy_msg = check_password_policy(new_password)
    if not ok_policy:
        return error_response(policy_msg, 400)

    if not check_password_hash(user.password_hash, old_password):
        return error_response('旧密码错误', 400)

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    # 清除该用户全部 Redis 会话，强制重新登录
    from modules.system.session_cache import delete_user_sessions
    delete_user_sessions(user.id)

    return success_response(msg='密码修改成功，请重新登录')


def health_check():
    """健康检查"""
    from core.redis_client import status
    return jsonify({
        'code': 200,
        'msg': 'success',
        'data': {
            'status': 'healthy',
            'timestamp': datetime.datetime.now().isoformat(),
            'service': 'ops-platform',
            'redis': status(),
        }
    })
