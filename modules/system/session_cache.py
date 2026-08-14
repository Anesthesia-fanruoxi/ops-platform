# -*- coding: utf-8 -*-
"""
登录会话 Redis 缓存（认证会话以 Redis 为准，MySQL auth_tokens 表已废弃）

- 登录：写缓存 + 维护「用户→token 集合」索引，用于改密/禁用/删号时批量失效。
- 鉴权：优先读缓存构造会话用户快照，未命中回源 DB 并回填。
- Redis 不可用：全部静默降级，鉴权走 DB 原逻辑，业务不受影响。
"""
from core.redis_client import (
    cache_get, cache_get_json, cache_set_json, cache_delete,
    sadd, srem, smembers,
    increment, set_if_absent, expire,
)

# 登录失败锁定阈值与窗口（秒）
LOGIN_MAX_FAILS = 5
LOGIN_LOCK_TTL = 900


def _token_key(token):
    return f'auth:token:{token}'


def _user_tokens_key(user_id):
    return f'auth:user_tokens:{user_id}'


def _fail_key(username):
    return f'auth:fail:{username}'


def _lock_key(username):
    return f'auth:lock:{username}'


class _SessionRole:
    """轻量角色快照（仅承载鉴权所需字段）"""

    def __init__(self, name, permissions):
        self.name = name or ''
        self._permissions = permissions or []

    def permissions_list(self):
        return list(self._permissions)


class SessionUser:
    """由缓存构造的会话用户快照（非 ORM 对象，字段与 User 对齐）"""

    def __init__(self, data):
        self.id = data['user_id']
        self.username = data.get('username', '')
        self.nickname = data.get('nickname', '')
        self.role_id = data.get('role_id')
        self.is_active = data.get('is_active', True)
        self.auth_source = data.get('auth_source', 'local')
        role = data.get('role') or {}
        self.role = _SessionRole(role.get('name'), role.get('permissions')) if role else None
        # 超级管理员：优先取独立表标记（super_admins）；兼容旧会话（「超级管理员」角色驱动）
        self.is_super_admin = bool(data.get('is_super_admin', False)) or bool(self.role and self.role.name == '超级管理员')

    def apply_real_time(self, db_user):
        """用 DB 实时数据覆盖会话快照（禁用状态 + 角色权限），供每次请求原子校验。

        - is_active：平台禁用 / 认证中心同步禁用即时生效（无需踢会话、无需等过期）
        - role/permissions：角色变更（含角色被移除/置空）即时生效，防止旧权限残留
        """
        self.is_active = bool(db_user.is_active)
        if db_user.role is not None:
            self.role = _SessionRole(db_user.role.name, db_user.role.permissions_list())
            self.is_super_admin = (db_user.role.name == '超级管理员')
        else:
            # 角色被移除/置空：必须清空快照权限，否则旧 _SessionRole（含全部权限）残留 → 越权
            self.role = None
            self.is_super_admin = False
        self.role_id = db_user.role_id
        self.role_name = db_user.role.name if db_user.role else '未分配'

    def display_name(self):
        return (self.nickname or '').strip() or self.username

    def to_dict(self, include_permissions=False):
        data = {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname or '',
            'role_id': self.role_id,
            'role_name': self.role.name if self.role else '未分配',
            'is_active': self.is_active,
            'is_super_admin': self.is_super_admin,
            'created_at': None,
        }
        if include_permissions and self.role:
            data['permissions'] = self.role.permissions_list()
        return data


def save_session(token, user, expires_at, ttl):
    """登录成功后写入会话缓存（含权限快照），并登记用户→token 索引。
    返回是否写入成功（Redis 不可用时返回 False，登录应拒绝发 token）。"""
    payload = {
        'user_id': user.id,
        'username': user.username,
        'nickname': user.nickname or '',
        'role_id': getattr(user, 'role_id', None),
        'is_active': bool(user.is_active),
        'auth_source': getattr(user, 'auth_source', None) or 'local',
        'is_super_admin': bool(getattr(user, 'is_super_admin', False)),
        'role': {
            'name': getattr(user.role, 'name', '') if getattr(user, 'role', None) else '',
            'permissions': getattr(user.role, 'permissions_list', lambda: [])() if getattr(user, 'role', None) else [],
        },
        'expires_at': expires_at.strftime('%Y-%m-%d %H:%M:%S'),
    }
    ok = cache_set_json(_token_key(token), payload, ttl=ttl)
    if ok:
        sadd(_user_tokens_key(user.id), token)
        # 索引集与会话生命周期对齐：避免 token 过期后 set 永久驻留 Redis
        expire(_user_tokens_key(user.id), ttl)
    return ok


def get_session(token):
    """读取会话缓存：命中返回 payload dict；不存在/异常返回 None。
    过期判定以 Redis TTL 为准（请求时滑动续期，见 refresh_session）。"""
    data = cache_get_json(_token_key(token))
    if not data:
        return None
    return data


def get_session_user(token):
    """读取会话并构造 SessionUser；未命中返回 None"""
    data = get_session(token)
    if not data:
        return None
    try:
        return SessionUser(data)
    except (KeyError, TypeError, ValueError):
        delete_session(token, data.get('user_id'))
        return None


def delete_session(token, user_id=None):
    """登出/单 token 失效：删缓存 + 从用户索引移除"""
    if user_id is None:
        data = cache_get_json(_token_key(token))
        user_id = (data or {}).get('user_id')
    cache_delete(_token_key(token))
    if user_id is not None:
        srem(_user_tokens_key(user_id), token)


def delete_user_sessions(user_id):
    """改密/禁用/删号：删除该用户全部会话缓存（惰性清理已过期的死 token）"""
    key = _user_tokens_key(user_id)
    tokens = smembers(key)
    live = []
    for t in tokens:
        if cache_get(_token_key(t)) is not None:
            live.append(t)
        else:
            srem(key, t)  # 死成员（token 已自然过期）顺手清掉
    if live:
        cache_delete(*[_token_key(t) for t in live])
    cache_delete(key)


def refresh_session(token, ttl=None):
    """请求时重置会话 TTL（滑动过期）：每次有效请求将过期时间恢复为完整会话时长。
    ttl 缺省取平台设置 token_expire_hours；Redis 不可用/键不存在返回 False。"""
    if ttl is None:
        from modules.system.settings_service import get_setting_int
        hours = get_setting_int('token_expire_hours', 8) or 8
        ttl = hours * 3600
    if not expire(_token_key(token), ttl):
        return False
    # 索引集随会话滑动续期，确保活跃会话期间不被误删
    data = cache_get_json(_token_key(token))
    user_id = (data or {}).get('user_id')
    if user_id is not None:
        expire(_user_tokens_key(user_id), ttl)
    return True


# ─── 登录限流 ────────────────────────────────────────────────

def is_login_locked(username):
    """是否处于锁定状态；Redis 不可用返回 False（不拦截）"""
    return bool(cache_get(_lock_key(username)))


def record_login_fail(username):
    """记录一次失败；达阈值置锁定标记。Redis 不可用返回 False"""
    count = increment(_fail_key(username), ttl=LOGIN_LOCK_TTL)
    if count is None:
        return False
    if count >= LOGIN_MAX_FAILS:
        set_if_absent(_lock_key(username), '1', ttl=LOGIN_LOCK_TTL * 1000)
    return True


def clear_login_fail(username):
    """登录成功后清除失败计数与锁定标记"""
    cache_delete(_fail_key(username), _lock_key(username))
