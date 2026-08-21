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
from core.audit import record_auth_event
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


def _finish_login(user, username, action='login'):
    """凭证校验通过后的统一收尾：发本地会话。各登录入口（本地/admin/sso 映射）共用。"""
    issued = _issue_local_session(user)
    if not issued:
        record_auth_event(action, 'failed', '认证服务暂不可用（Redis 异常）', username=username)
        return error_response('认证服务暂不可用（Redis 异常），请稍后再试', 503)
    token_str, expires_at = issued
    from modules.system.session_cache import clear_login_fail
    clear_login_fail(username)
    record_auth_event(action, 'success', f'用户 {username} 登录成功', username=username)
    from modules.system.settings_service import get_password_policy
    return success_response({
        'token': token_str,
        'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
        'user': user.to_dict(include_permissions=True),
        'password_policy': get_password_policy(),
    }, '登录成功')


def login_2fa():
    """双因子登录第二步：提交认证中心多步登录 ticket + 6 位验证码，由认证中心完成校验。
    平台不存密钥、不验验证码，仅透传认证中心结果并映射本地用户发会话。
    请求体: {"ticket": "...", "code": "123456"}"""
    data = request.json or {}
    ticket = (data.get('ticket') or '').strip()
    code = str(data.get('code') or '').strip()
    if not ticket or not code:
        return error_response('验证凭证与验证码不能为空', 400)

    from modules.system.auth_platform import get_config, verify_login_step2, get_or_create_sso_user
    authp_cfg = get_config()
    if not authp_cfg:
        return error_response('未接入统一鉴权中心，无需双因子验证', 400)

    result = verify_login_step2(ticket, code, authp_cfg['platform_id'])
    if result is None:
        return error_response('认证服务配置异常，请联系管理员', 503)
    if not result['ok']:
        return _authp_error_response(result)

    user = get_or_create_sso_user(result['user'])
    if not user:
        return error_response('登录失败：无法映射用户身份，请联系管理员', 403)
    if not user.is_active:
        return error_response('账号已被禁用，请联系管理员', 403)
    if result.get('must_change_password'):
        return error_response('需先修改密码后才能登录，请联系管理员', 403)
    return _finish_login(user, user.username)


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

    双因子登录（登录页「双因子登录」标签，免密码）：仅提交 username + code 时，
    透传认证中心按 totp 登录类型校验；请求体附带 password + code 时一步完成两步校验。
    """
    data = request.json or {}
    # 统一转小写：MySQL collation 大小写不敏感，避免 'Admin'/'ADMIN' 变体绕过限流锁定键（auth:fail:{username}）
    username = data.get('username', '').strip().lower()
    password = data.get('password', '')
    code_2fa = str(data.get('code') or '').strip()

    if not username:
        return error_response('用户名不能为空', 400)
    if not password and not code_2fa:
        return error_response('密码或验证码至少提供一项', 400)

    # 登录限流（Redis 不可用时自动跳过，不拦截；authPlatform 侧也有账号维度锁定）
    from modules.system.session_cache import (
        is_login_locked, record_login_fail, clear_login_fail, save_session,
        delete_user_sessions,
    )
    if is_login_locked(username):
        record_auth_event('login', 'failed', '尝试次数过多被锁定', username=username)
        return error_response('尝试次数过多，请15分钟后再试', 429)

    # ── 统一鉴权中心（authPlatform）接入：配置了接入参数则优先走平台校验 ──
    from modules.system.auth_platform import verify_login, get_config, get_or_create_sso_user
    authp_cfg = get_config()
    if authp_cfg:
        # 逃生通道：本地原生账号（auth_source='local'，如 admin）始终走本地校验，
        # 保证配置期/鉴权中心故障期间管理员仍可登录调整配置，避免「配置了统一登录却登录不进去」的锁死
        local_user = User.query.filter_by(username=username).first()
        if local_user and local_user.auth_source == 'local':
            if not password:
                return error_response('本地账号不支持双因子登录，请使用账号密码登录', 400)
            if not check_password_hash(local_user.password_hash, password):
                record_login_fail(username)
                record_auth_event('login', 'failed', '用户名或密码错误', username=username)
                return error_response('用户名或密码错误', 401)
            if not local_user.is_active:
                record_auth_event('login', 'failed', '账号已被禁用', username=username)
                return error_response('账号已被禁用，请联系管理员', 403)
            return _finish_login(local_user, username)

        # sso 用户或本地不存在的账号 → 转发 authPlatform 校验：
        # 仅验证码无密码 → 「双因子登录」标签，按 totp 登录类型一步校验；
        # 有密码 → 密码登录（附带 code 时可一步完成两步校验）
        if code_2fa and not password:
            from modules.system.auth_platform import verify_login_totp
            result = verify_login_totp(username, code_2fa, authp_cfg['platform_id'])
        else:
            result = verify_login(username, password, authp_cfg['platform_id'])
        if result is None:
            record_auth_event('login', 'failed', '认证服务配置异常', username=username)
            return error_response('认证服务配置异常，请联系管理员', 503)
        if not result['ok']:
            record_login_fail(username)
            record_auth_event('login', 'failed', (result.get('msg') or '登录失败')[:100], username=username)
            return _authp_error_response(result)

        # 认证中心要求双因子（多步登录）：
        # 附带 code → 一步提交（「双因子登录」标签），直接拿 ticket + 验证码走第二步；
        # 未附带 code → 透传 ticket，前端引导输入验证码后调 /login-2fa
        if result.get('require_2fa'):
            if code_2fa:
                from modules.system.auth_platform import verify_login_step2
                result = verify_login_step2(result['ticket'], code_2fa, authp_cfg['platform_id'])
                if result is None:
                    return error_response('认证服务配置异常，请联系管理员', 503)
                if not result['ok']:
                    record_login_fail(username)
                    record_auth_event('login', 'failed', (result.get('msg') or '双因子验证失败')[:100], username=username)
                    return _authp_error_response(result)
                # 第二步成功，继续下方映射本地用户 → 发会话
            else:
                return success_response(
                    {'require_2fa': True, 'ticket': result['ticket']}, '请输入双因子验证码')

        # 登录成功：映射本地用户 → 发本地会话
        user = get_or_create_sso_user(result['user'])
        if not user:
            record_auth_event('login', 'failed', '无法映射用户身份', username=username)
            return error_response('登录失败：无法映射用户身份，请联系管理员', 403)
        if not user.is_active:
            record_auth_event('login', 'failed', '账号已被禁用', username=username)
            return error_response('账号已被禁用，请联系管理员', 403)
        if result.get('must_change_password'):
            record_auth_event('login', 'failed', '需先修改密码', username=username)
            return error_response('需先修改密码后才能登录，请联系管理员', 403)
        return _finish_login(user, username)

    # ── 未接入 authPlatform：走本地账号校验（原逻辑）──
    if not password:
        return error_response('未接入统一鉴权中心，请使用账号密码登录', 400)
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        record_login_fail(username)
        record_auth_event('login', 'failed', '用户名或密码错误', username=username)
        return error_response('用户名或密码错误', 401)

    if not user.is_active:
        record_auth_event('login', 'failed', '账号已被禁用', username=username)
        return error_response('账号已被禁用，请联系管理员', 403)

    return _finish_login(user, username)


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
        record_auth_event('admin_login', 'failed', '尝试次数过多被锁定', username=username)
        return error_response('尝试次数过多，请15分钟后再试', 429)

    # 超级管理员独立表（super_admins）：本地账号本地校验，不受认证中心影响
    from modules.system.models import SuperAdmin
    sa = SuperAdmin.query.filter_by(username=username).first()
    if not sa:
        # 统一失败响应（不区分超管与否）防用户名枚举；不记计数防被刷锁号（DoS）
        return error_response('账号或密码错误', 401)

    if not sa.check_password(password):
        record_login_fail(username)
        record_auth_event('admin_login', 'failed', '账号或密码错误', username=username)
        return error_response('账号或密码错误', 401)

    if not sa.is_active:
        return error_response('账号已被禁用，请联系管理员', 403)

    return _finish_login(sa, username, 'admin_login')


def logout():
    """登出：删除当前 Token"""
    from core.security import _get_token_from_request
    token_str = _get_token_from_request(request)
    if token_str:
        from modules.system.session_cache import delete_session
        delete_session(token_str)
    current = getattr(g, 'current_user', None)
    record_auth_event('logout', 'success', '用户退出登录',
                      username=(current.username if current else ''))
    return success_response(msg='已退出登录')


def me():
    """获取当前登录用户信息（含权限 + 密码策略）"""
    user = getattr(g, 'current_user', None)
    if not user:
        return error_response('未登录', 401)
    data = user.to_dict(include_permissions=True)
    from modules.system.settings_service import get_password_policy
    data['password_policy'] = get_password_policy()
    return success_response(data)


def change_password():
    """
    修改密码（登录态直接改，不验证旧密码）
    - sso（认证中心账号）：转发 authPlatform update-profile，认证中心落库后删除本地会话
    - local（超管/本机账号）：改本地 users.password_hash
    请求体: {"new_password": "..."}
    """
    current = getattr(g, 'current_user', None)
    if not current:
        return error_response('未登录', 401)

    data = request.json or {}
    new_password = data.get('new_password', '').strip()
    if not new_password:
        return error_response('新密码不能为空', 400)

    from modules.system.settings_service import check_password_policy
    ok_policy, policy_msg = check_password_policy(new_password)
    if not ok_policy:
        return error_response(policy_msg, 400)

    # 超级管理员（super_admins 独立账号）：本地改密（认证中心无此账号）
    if getattr(current, 'is_super_admin', False):
        from modules.system.models import SuperAdmin
        sa = SuperAdmin.query.get(current.id)
        if not sa:
            return error_response('管理员账号不存在', 404)
        sa.password_hash = generate_password_hash(new_password)
        db.session.commit()
        record_auth_event('change_password', 'success', '修改密码成功（超级管理员）', username=current.username)
        from modules.system.session_cache import delete_user_sessions
        delete_user_sessions(sa.id)
        return success_response(msg='密码修改成功，请重新登录')

    # 回源 DB 取 ORM 用户（g.current_user 是 Redis 会话快照，无 password_hash）
    user = User.query.get(current.id)
    if not user:
        return error_response('用户不存在', 404)

    # sso（认证中心账号）：密码在认证中心，转发修改
    if user.auth_source != 'local':
        from modules.system.auth_platform import update_profile
        result = update_profile(user.username, password=new_password)
        if result is None:
            return error_response('未配置认证中心（authPlatform），无法修改密码', 400)
        if not result['ok']:
            return error_response(result['msg'], 502)
        record_auth_event('change_password', 'success', '修改密码成功（认证中心）', username=current.username)
        # 认证中心改密成功：删除该用户本地全部会话，强制重新登录
        from modules.system.session_cache import delete_user_sessions
        delete_user_sessions(user.id)
        return success_response(msg='密码修改成功，请重新登录')

    # local（超管/本机账号）：改本地密码哈希
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    record_auth_event('change_password', 'success', '修改密码成功', username=current.username)
    from modules.system.session_cache import delete_user_sessions
    delete_user_sessions(user.id)
    return success_response(msg='密码修改成功，请重新登录')


def health_check():
    """多维度健康检查：DB/Redis 连接池、线程、异步任务、请求延迟、核心下游连通"""
    from modules.system.healthz import run_checks
    result = run_checks()
    http_code = 200 if result['status'] in ('healthy', 'degraded') else 503
    return jsonify({
        'code': http_code,
        'msg': 'success' if http_code == 200 else 'service unhealthy',
        'data': result,
    })
