# -*- coding: utf-8 -*-
"""
authPlatform（统一鉴权中心）接入客户端

- 平台代理校验：登录时把账号密码转发给 authPlatform，成功后把用户映射到本地 users 表，
  本地会话仍走现有 Redis 会话机制（session_cache），不保存 authPlatform 的 token。
- 所有请求带 HMAC-SHA256 签名（X-Platform-Id / X-Timestamp / X-Sign），防伪造 + 防重放。
- 未配置接入参数（base_url/platform_id/secret 任一为空）视为未接入，调用方回退本地校验。
"""
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime

import requests


def get_config():
    """读取 authPlatform 接入配置；任一必填项缺失返回 None（未接入）"""
    from modules.system.settings_service import get_setting
    base_url = (get_setting('authplatform_base_url') or '').strip().rstrip('/')
    platform_id = (get_setting('authplatform_platform_id') or '').strip()
    secret = (get_setting('authplatform_secret') or '').strip()
    if not base_url or not platform_id or not secret:
        return None
    return {'base_url': base_url, 'platform_id': platform_id, 'secret': secret}


def _sign(secret, method, uri, timestamp, body_bytes):
    """HMAC-SHA256 签名：sign = HMAC(secret, method|URI|ts|sha256(body))"""
    msg = f"{method}|{uri}|{timestamp}|{hashlib.sha256(body_bytes).hexdigest()}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _request(cfg, method, uri, body=None):
    """带签名调用 authPlatform；HTTP 层错误抛出异常，业务层返回统一 JSON"""
    body_bytes = json.dumps(body).encode('utf-8') if body is not None else b''
    ts = str(int(time.time()))
    headers = {
        'X-Platform-Id': cfg['platform_id'],
        'X-Timestamp': ts,
        'X-Sign': _sign(cfg['secret'], method, uri, ts, body_bytes),
        'Content-Type': 'application/json',
    }
    url = cfg['base_url'] + uri
    if method == 'POST':
        resp = requests.post(url, data=body_bytes, headers=headers, timeout=5)
    else:
        resp = requests.get(url, headers=headers, timeout=5)
    resp.raise_for_status()
    return resp.json()


def _parse_verify_data(data):
    """解析 /api/auth/verify 成功响应：单步返回 token，多步（双因子）返回 ticket"""
    d = data.get('data') or {}
    # 多步登录（双因子）：认证中心返回 ticket 而非 token，需第二步提交验证码
    if 'token' not in d:
        ticket = d.get('ticket') or ''
        if ticket:
            return {'ok': True, 'require_2fa': True, 'ticket': ticket}
        return {'ok': False, 'code': 'error', 'msg': '认证服务响应异常，请稍后再试'}
    user = d.get('user') or {}
    return {
        'ok': True,
        'require_2fa': False,
        'token': d.get('token'),
        'expires_at': d.get('expires_at'),
        'user': user,
        'must_change_password': bool(user.get('must_change_password')),
    }


def verify_login(username, password, platform_id):
    """登录校验第一步（username_password 类型，兼容 authPlatform 旧格式）。

    Returns:
        None: 未配置 authPlatform（调用方应回退本地校验）
        dict 单步成功: {'ok': True, 'require_2fa': False, 'token', 'expires_at', 'user', 'must_change_password'}
        dict 需双因子: {'ok': True, 'require_2fa': True, 'ticket'}（调用方引导第二步）
        dict 失败: {'ok': False, 'code', 'msg'}
    """
    cfg = get_config()
    if not cfg:
        return None

    try:
        data = _request(cfg, 'POST', '/api/auth/verify', {
            'platform_id': platform_id,
            'method': 'username_password',
            'identifier': username,
            'credential': password,
        })
    except Exception as e:
        # 不把异常细节透传给用户（可能含内网 URL），仅记日志
        try:
            import logging
            logging.getLogger('authplatform').warning('authPlatform verify 调用失败: %s', e)
        except Exception:
            pass
        return {'ok': False, 'code': 'error', 'msg': '认证服务调用失败，请稍后再试'}

    code = data.get('code')
    if code == 0:
        return _parse_verify_data(data)

    # 业务错误（含 1010 强制改密、1001-1009）
    return {
        'ok': False,
        'code': 'must_change_password' if code == 1010 else code,
        'msg': data.get('msg') or f'登录失败(code={code})',
        'user': data.get('data') or {},
    }


def verify_login_totp(username, code_2fa, platform_id):
    """TOTP 双因子登录（免密码）：同一 /api/auth/verify 接口，按登录类型区分（username + code）。
    验证码由认证中心校验（平台不存密钥、不验码），成功返回 token + user。

    Returns: 与 verify_login 单步成功/失败同结构（不会再返回 require_2fa）
    """
    cfg = get_config()
    if not cfg:
        return None

    try:
        data = _request(cfg, 'POST', '/api/auth/verify', {
            'platform_id': platform_id,
            'method': 'username_totp',
            'identifier': username,
            'credential': code_2fa,
        })
    except Exception as e:
        try:
            import logging
            logging.getLogger('authplatform').warning('authPlatform verify(totp) 调用失败: %s', e)
        except Exception:
            pass
        return {'ok': False, 'code': 'error', 'msg': '认证服务调用失败，请稍后再试'}

    code = data.get('code')
    if code == 0:
        parsed = _parse_verify_data(data)
        if parsed.get('require_2fa'):
            return {'ok': False, 'code': 'error', 'msg': '认证服务响应异常，请重试'}
        return parsed

    return {
        'ok': False,
        'code': 'must_change_password' if code == 1010 else code,
        'msg': data.get('msg') or f'验证失败(code={code})',
        'user': data.get('data') or {},
    }


def verify_login_step2(ticket, code_2fa, platform_id):
    """登录校验第二步（双因子类型）：同一 /api/auth/verify 接口，提交第一步的 ticket + 验证码。
    验证码由认证中心校验（平台不存密钥、不验证），成功返回 token + user。

    Returns: 与 verify_login 单步成功/失败同结构（不会再返回 require_2fa）
    """
    cfg = get_config()
    if not cfg:
        return None

    try:
        data = _request(cfg, 'POST', '/api/auth/verify', {
            'platform_id': platform_id,
            'ticket': ticket,
            'code': code_2fa,
        })
    except Exception as e:
        try:
            import logging
            logging.getLogger('authplatform').warning('authPlatform verify(step2) 调用失败: %s', e)
        except Exception:
            pass
        return {'ok': False, 'code': 'error', 'msg': '认证服务调用失败，请稍后再试'}

    code = data.get('code')
    if code == 0:
        parsed = _parse_verify_data(data)
        # 第二步不应再要求双因子；异常兜底为错误
        if parsed.get('require_2fa'):
            return {'ok': False, 'code': 'error', 'msg': '认证服务响应异常，请重新登录'}
        return parsed

    return {
        'ok': False,
        'code': 'must_change_password' if code == 1010 else code,
        'msg': data.get('msg') or f'验证失败(code={code})',
        'user': data.get('data') or {},
    }


def list_users(keyword=None):
    """拉取本平台已授权用户列表（authPlatform 只返回授权给本平台且非敏感字段）。

    Returns:
        None: 未配置 authPlatform
        dict: {'ok': True, 'users': [...]} 或 {'ok': False, 'msg': ...}
    """
    cfg = get_config()
    if not cfg:
        return None

    uri = f"/api/users?platform_id={cfg['platform_id']}"
    if keyword:
        uri += f"&keyword={urllib.parse.quote(keyword)}"
    try:
        data = _request(cfg, 'GET', uri)
    except Exception as e:
        try:
            import logging
            logging.getLogger('authplatform').warning('authPlatform 拉取用户失败: %s', e)
        except Exception:
            pass
        return {'ok': False, 'msg': '认证服务调用失败，请稍后再试'}

    if data.get('code') == 0:
        return {'ok': True, 'users': (data.get('data') or {}).get('users') or []}
    return {'ok': False, 'msg': data.get('msg') or f'拉取失败(code={data.get("code")})'}


def sync_users():
    """全量同步认证中心用户：

    1. synced_users：只读副本（认证中心用户快照）
    2. users 表：复制 username/nickname 为 sso 用户（auth_uid 关联、无本地密码），
       供平台单独维护角色权限（如分配管理员角色）

    同名本地原生账号（auth_source='local'）冲突时跳过 users 复制（防止越权接管），
    仅保留 synced_users 记录。

    Returns:
        (None, msg): 未配置 authPlatform
        (False, msg): 拉取失败
        (True, msg): 同步完成统计
    """
    from core.db import db
    from modules.system.models import SyncedUser, User, Role

    result = list_users()
    if result is None:
        return None, '未配置认证中心（authPlatform），请先在平台设置中配置'
    if not result['ok']:
        return False, result['msg']

    now = datetime.now()
    created = 0
    updated = 0
    user_created = 0
    user_updated = 0
    skipped = []
    default_role = Role.query.filter_by(name='普通用户').first()

    for item in result['users']:
        uid = (item or {}).get('uid')
        if not uid:
            continue
        username = (item.get('username') or '').strip()
        nickname = item.get('nickname') or ''
        nickname_pinyin = item.get('nickname_pinyin') or ''  # 认证中心解析的完整拼音
        phone = item.get('phone') or ''
        email = item.get('email') or ''
        try:
            raw_status = item.get('status', 1)
            status = int(raw_status) if raw_status is not None and str(raw_status).strip() != '' else 1
        except (TypeError, ValueError):
            status = 1
        src_created = item.get('created_at')

        # 1) synced_users 只读副本（upsert by uid）
        row = SyncedUser.query.filter_by(uid=uid).first()
        if row:
            row.username = username or row.username
            row.nickname = nickname
            row.nickname_pinyin = nickname_pinyin
            row.phone = phone
            row.email = email
            row.status = status
            row.last_synced_at = now
            updated += 1
        else:
            parsed_created = None
            if src_created:
                try:
                    parsed_created = datetime.strptime(str(src_created)[:19], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    parsed_created = None
            db.session.add(SyncedUser(
                uid=uid,
                username=username,
                nickname=nickname,
                nickname_pinyin=nickname_pinyin,
                phone=phone,
                email=email,
                status=status,
                created_at=parsed_created,
                last_synced_at=now,
            ))
            created += 1

        # 2) users 表复制（sso 用户，供平台分配角色）
        #    停用合并规则：任一禁用即禁用（认证中心启用不覆盖平台已禁，认证中心禁用强制平台禁用）
        local = User.query.filter_by(auth_uid=uid).first()
        if local:
            if username and username != local.username:
                local.username = username
            local.nickname = nickname
            local.nickname_pinyin = nickname_pinyin
            local.phone = phone
            local.email = email
            local.is_active = bool(status) and local.is_active
            user_updated += 1
        else:
            clash = User.query.filter_by(username=username).first() if username else None
            if clash and clash.auth_source != 'sso':
                # 同名本地原生账号：跳过 users 复制（防越权接管），synced_users 仍保留
                skipped.append(username)
                continue
            if clash:  # 已标记 sso 的旧账号：重绑 auth_uid
                clash.auth_uid = uid
                clash.nickname = nickname
                clash.nickname_pinyin = nickname_pinyin
                clash.phone = phone
                clash.email = email
                clash.is_active = bool(status) and clash.is_active
                user_updated += 1
            else:
                db.session.add(User(
                    username=username,
                    nickname=nickname,
                    nickname_pinyin=nickname_pinyin,
                    phone=phone,
                    email=email,
                    password_hash='',  # sso 用户无本地密码，登录走认证中心
                    auth_uid=uid,
                    auth_source='sso',
                    role_id=default_role.id if default_role else None,
                    is_active=bool(status),  # 新用户无平台禁用历史，跟随认证中心状态
                ))
                user_created += 1

    db.session.commit()

    # ── 全量镜像覆盖：删除认证中心已不返回的记录（取消授权 / 移除用户）──
    remote_uids = {item.get('uid') for item in result['users'] if item.get('uid')}
    deleted_sync = 0
    # 1) synced_users 只读镜像：多余即删（纯快照，无本地业务状态）
    if remote_uids:
        stale_rows = SyncedUser.query.filter(~SyncedUser.uid.in_(remote_uids)).all()
    else:
        stale_rows = SyncedUser.query.all()
    for row in stale_rows:
        db.session.delete(row)
        deleted_sync += 1
    # 2) users 表 sso 用户：多余即删——取消授权/移除 → 平台彻底移除（含已分配角色的，重新授权后重建为默认只读角色）
    user_deleted = 0
    for u in User.query.filter(User.auth_source == 'sso').all():
        if u.auth_uid in remote_uids:
            continue
        db.session.delete(u)
        user_deleted += 1
    if deleted_sync or user_deleted:
        db.session.commit()

    # 注：认证中心禁用/删除不在此主动踢会话——删除用户后由实时校验（用户不存在→401）拦截，
    # 禁用用户由实时禁用校验拦截（认证中心禁用=全台禁用，经各平台同步落地）
    msg = f'同步完成：新增 {created} 个、更新 {updated} 个'
    if user_created or user_updated:
        msg += f'；平台用户新增 {user_created} 个、更新 {user_updated} 个'
    if deleted_sync:
        msg += f'；移除已取消授权 {deleted_sync} 个'
    if user_deleted:
        msg += f'；平台用户删除 {user_deleted} 个'
    if skipped:
        msg += f'；跳过同名本地账号 {len(skipped)} 个（{", ".join(skipped[:5])}）'
    return True, msg


def update_profile(username, nickname=None, email=None, phone=None, password=None, totp_secret=None):
    """提交用户资料变更到 authPlatform（POST /api/auth/update-profile）。

    约定：变更逻辑在平台处理、数据在认证中心存储。
    - email/phone：None=不修改；''=清空；非空=更新
    - password：非空则代改密码（管理员场景，认证中心直接哈希存储）
    - totp_secret：非空=重新绑定并启用；''=清除

    Returns:
        None: 未配置 authPlatform
        dict: {'ok': True, 'user': ...} 或 {'ok': False, 'code', 'msg'}
    """
    cfg = get_config()
    if not cfg:
        return None

    body = {'username': username, 'platform_id': cfg['platform_id']}
    if nickname is not None:
        body['nickname'] = nickname
    if email is not None:
        body['email'] = email
    if phone is not None:
        body['phone'] = phone
    if password:
        body['password'] = password
    if totp_secret is not None:
        body['totp_secret'] = totp_secret

    try:
        data = _request(cfg, 'POST', '/api/auth/update-profile', body)
    except Exception as e:
        try:
            import logging
            logging.getLogger('authplatform').warning('authPlatform update-profile 调用失败: %s', e)
        except Exception:
            pass
        return {'ok': False, 'code': 'error', 'msg': '认证服务调用失败，请稍后再试'}

    if data.get('code') == 0:
        return {'ok': True, 'user': data.get('data') or {}}
    return {'ok': False, 'code': data.get('code'), 'msg': data.get('msg') or '更新失败'}


def get_or_create_sso_user(user_info):
    """把 authPlatform 用户映射到本地 users 表（auth_uid 唯一）。

    - auth_uid 已映射 → 返回本地用户（同步昵称）
    - 本地存在同名 username 且已标记 sso 的账号 → 重绑 auth_uid（断链修复，沿用角色）
    - 本地同名原生账号（auth_source='local'）→ 拒绝自动绑定，返回 None（防止越权接管）
    - 都没有 → 新建（默认角色：普通用户，最小权限，管理员可在平台内提权）
    """
    from core.db import db
    from modules.system.models import User, Role

    uid = (user_info or {}).get('uid') or ''
    username = ((user_info or {}).get('username') or '').strip()
    nickname = (user_info or {}).get('nickname') or ''
    if not uid or not username:
        return None

    user = User.query.filter_by(auth_uid=uid).first()
    if user:
        if nickname and nickname != user.nickname:
            user.nickname = nickname
            db.session.commit()
        # 拼音以认证中心为准，同步更新（登录映射场景）
        pinyin = (user_info or {}).get('nickname_pinyin') or ''
        if pinyin and pinyin != user.nickname_pinyin:
            user.nickname_pinyin = pinyin
            db.session.commit()
        return user

    # 同名本地旧账号：仅允许「已标记 sso 的账号」重绑（断链修复）；
    # 本地原生账号（auth_source='local'）一律不自动绑定——防止 SSO 同名账号越权接管本地账号及其角色，
    # 冲突时由管理员在用户管理中处理
    user = User.query.filter_by(username=username).first()
    if user:
        if user.auth_source != 'sso':
            return None
        user.auth_uid = uid
        db.session.commit()
        return user

    role = Role.query.filter_by(name='普通用户').first()
    user = User(
        username=username,
        nickname=nickname,
        nickname_pinyin=(user_info or {}).get('nickname_pinyin') or '',
        password_hash='',  # 无本地密码，登录统一走 authPlatform
        auth_uid=uid,
        auth_source='sso',
        role_id=role.id if role else None,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user
