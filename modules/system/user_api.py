# -*- coding: utf-8 -*-
"""
用户管理接口处理函数
"""
from flask import request, g
from werkzeug.security import generate_password_hash
from core.db import db
from modules.system.models import User, Role
from core.response import success_response, error_response
from core.security import require_permission


@require_permission('op:users')
def list_users():
    """获取所有用户列表（超级管理员为内置逃生账号，不展示）"""
    users = User.query.order_by(User.id.asc()).all()
    visible = [u.to_dict() for u in users if not u.is_super_admin]
    return success_response(visible)


@require_permission('op:users')
def create_user():
    """创建用户（已禁用：平台用户由认证中心同步管理，经「同步认证中心用户」填充）"""
    return error_response('用户由认证中心同步管理，请先「同步认证中心用户」再在平台内分配角色', 400)


@require_permission('op:users')
def update_user(user_id):
    """
    更新用户（修改用户名、昵称、角色、启用状态）
    请求体: {"username": "...", "nickname": "...", "role_id": 1, "is_active": true}
    """
    user = User.query.get(user_id)
    if not user:
        return error_response('用户不存在', 404)
    if user.is_super_admin:
        return error_response('超级管理员账号不可编辑（仅系统管理，如需调整请直接修改数据库）', 400)

    current_user = getattr(g, 'current_user', None)
    current_id = current_user.id if current_user else None

    data = request.json or {}
    username = data.get('username', '').strip()
    nickname = data.get('nickname')
    role_id = data.get('role_id')
    is_active = data.get('is_active')

    name_changed = False
    role_changed = False
    active_changed = False

    if username and username != user.username:
        if User.query.filter(User.username == username, User.id != user_id).first():
            return error_response(f'用户名「{username}」已存在', 400)
        user.username = username
        name_changed = True

    if nickname is not None:
        nickname = nickname.strip()
        if nickname != (user.nickname or ''):
            user.nickname = nickname

    if role_id is not None:
        if role_id == '':
            new_role_id = None
        else:
            role = Role.query.get(role_id)
            if not role:
                return error_response('指定角色不存在', 400)
            if role.name == '超级管理员':
                return error_response('「超级管理员」角色不可通过用户编辑分配（仅初始化/数据库指定，且不可降级）', 400)
            new_role_id = role_id
        if user.role_id != new_role_id:
            user.role_id = new_role_id
            role_changed = True

    if is_active is not None:
        new_active = bool(is_active)
        if user.is_active != new_active:
            user.is_active = new_active
            if not new_active:
                active_changed = True  # 仅禁用需要清会话；启用不需要

    db.session.commit()

    # 会话策略：仅修改密码才会使 token 失效（用户规则）；
    # 角色/昵称/用户名等资料变更一律不清会话（编辑自己或他人都不会导致被登出）。
    # 例外：禁用账号（is_active→false）属于吊销访问，立即清会话踢下线；启用不清。
    if active_changed:
        from modules.system.session_cache import delete_user_sessions
        delete_user_sessions(user.id)
    return success_response(user.to_dict(), '用户更新成功')


@require_permission('op:users')
def delete_user(user_id):
    """删除用户（已禁用：平台用户由认证中心同步管理，如需移除请停用）"""
    return error_response('用户由认证中心同步管理，不支持手动删除；如需移除请停用该用户', 400)


@require_permission('op:users')
def sync_users_from_auth():
    """从认证中心（authPlatform）拉取用户表到 synced_users（只读副本，仅拉取接口写入）"""
    from modules.system.auth_platform import sync_users
    ok, msg = sync_users()
    if ok is None:
        return error_response(msg, 400)
    if not ok:
        return error_response(msg, 502)
    return success_response(msg=msg)


@require_permission('page:users')
@require_permission('op:users')
def update_profile_from_auth(user_id):
    """修改用户资料（非平台特性字段：手机号/邮箱/密码/TOTP 重新绑定）

    逻辑在平台处理、数据在认证中心存储：平台把变更提交 authPlatform update-profile，
    认证中心落库后返回成功；随后平台同步一次用户表更新本地副本。
    角色/停用等平台特性字段仍走本平台的 /api/users/update。
    """
    from modules.system.auth_platform import update_profile, sync_users
    from modules.system.models import User

    user = User.query.get(user_id)
    if not user:
        return error_response('用户不存在', 404)
    if user.is_super_admin:
        return error_response('超级管理员账号不可修改', 400)
    if not user.auth_uid:
        return error_response('该用户非认证中心账号（sso），无法修改认证中心资料', 400)

    data = request.json or {}
    nickname = data.get('nickname')
    email = data.get('email')
    phone = data.get('phone')
    password = data.get('password')
    totp_secret = data.get('totp_secret')
    totp_code = data.get('totp_code')

    # 平台侧逻辑校验
    if email is not None:
        email = (str(email) or '').strip()
    if phone is not None:
        phone = (str(phone) or '').strip()
    if password:
        password = str(password)
        from modules.system.settings_service import check_password_policy
        ok_policy, policy_msg = check_password_policy(password)
        if not ok_policy:
            return error_response(policy_msg, 400)
    if totp_secret is not None:
        totp_secret = (str(totp_secret) or '').strip()
        if totp_secret and not totp_code:
            return error_response('TOTP 重新绑定需输入 6 位验证码确认', 400)
        if totp_secret and totp_code:
            try:
                import pyotp
                if not pyotp.TOTP(totp_secret).verify(str(totp_code).strip()):
                    return error_response('TOTP 验证码错误', 400)
            except Exception:
                return error_response('TOTP 验证码校验失败', 400)

    result = update_profile(
        user.username,
        nickname=nickname,
        email=email,
        phone=phone,
        password=password,
        totp_secret=totp_secret,
    )
    if result is None:
        return error_response('未配置认证中心（authPlatform），请先在平台设置中配置', 400)
    if not result['ok']:
        return error_response(result['msg'], 502)

    # 认证中心落库成功：同步一次用户表，更新本地副本
    sync_users()
    return success_response(msg='资料已更新（认证中心）')


@require_permission('op:users')
def totp_setup(user_id):
    """为认证中心用户生成 TOTP 重新绑定密钥（平台逻辑，认证中心仅存储）"""
    from modules.system.models import User

    user = User.query.get(user_id)
    if not user:
        return error_response('用户不存在', 404)
    if user.is_super_admin:
        return error_response('超级管理员账号不可操作', 400)
    if not user.auth_uid:
        return error_response('该用户非认证中心账号（sso），无法绑定 TOTP', 400)

    try:
        import pyotp
    except Exception:
        return error_response('服务器缺少 pyotp 依赖，无法生成 TOTP', 500)

    secret = pyotp.random_base32()
    otpauth_url = pyotp.TOTP(secret).provisioning_uri(
        name=user.username, issuer_name='authPlatform')
    return success_response({'secret': secret, 'otpauth_url': otpauth_url})


def list_synced_users():
    """只读：认证中心同步用户列表（synced_users，不参与登录与业务修改）"""
    from modules.system.models import SyncedUser
    users = SyncedUser.query.order_by(SyncedUser.username.asc()).all()
    return success_response([u.to_dict() for u in users])


@require_permission('op:users')
def reset_password(user_id):
    """重置密码（已禁用：平台用户密码由认证中心管理，仅超级管理员本人在平台设置中改密）"""
    return error_response('用户密码由认证中心管理，不支持在平台内重置', 400)
