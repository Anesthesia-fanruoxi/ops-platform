# -*- coding: utf-8 -*-
"""
系统管理域模型：Role / User / Setting（认证会话已迁移至 Redis，不再落 MySQL）
"""
import json
from datetime import datetime

from core.db import db


class Role(db.Model):
    """角色表"""
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200), default='')
    permissions = db.Column(db.Text, default='[]')  # JSON数组，如 ["page:create","op:deploy_project"]
    is_builtin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联用户
    users = db.relationship('User', backref='role', lazy=True)

    def permissions_list(self):
        try:
            return json.loads(self.permissions) if self.permissions else []
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'permissions': self.permissions_list(),
            'is_builtin': self.is_builtin,
            'user_count': len(self.users) if self.users else 0,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }


class User(db.Model):
    """用户表"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    nickname = db.Column(db.String(80), default='')
    nickname_pinyin = db.Column(db.String(128), default='')  # 认证中心解析的完整拼音（搜索用）
    password_hash = db.Column(db.String(256), nullable=False)
    auth_uid = db.Column(db.String(64), unique=True, nullable=True)  # 统一鉴权中心账号ID（sso 用户）
    auth_source = db.Column(db.String(16), default='local')  # local=本地账号 / sso=统一鉴权中心映射
    phone = db.Column(db.String(20), default='')  # 认证中心同步（手机号）
    email = db.Column(db.String(128), default='')  # 认证中心同步（邮箱）
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def display_name(self):
        """展示名称：昵称优先，无昵称回退用户名"""
        return (self.nickname or '').strip() or self.username

    @property
    def is_super_admin(self):
        """超级管理员：拥有「超级管理员」内置角色（本地逃生账号，仅系统管理权限）"""
        return self.role is not None and self.role.name == '超级管理员'

    @property
    def is_platform_admin(self):
        """兼容别名：同 is_super_admin"""
        return self.is_super_admin

    def to_dict(self, include_permissions=False):
        data = {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname or '',
            'nickname_pinyin': self.nickname_pinyin or '',
            'phone': self.phone or '',
            'email': self.email or '',
            'role_id': self.role_id,
            'role_name': self.role.name if self.role else '未分配',
            'is_active': self.is_active,
            'is_super_admin': self.is_super_admin,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
        if include_permissions and self.role:
            data['permissions'] = self.role.permissions_list()
        return data


class Setting(db.Model):
    """系统设置表"""
    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    type = db.Column(db.String(20), default='deploy', index=True)  # deploy/nginx/middleware/internal
    value = db.Column(db.Text, default='')
    description = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None
        }


class SyncedUser(db.Model):
    """认证中心同步用户表（只读：仅拉取接口写入，业务仅查询）

    用户信息以认证中心（authPlatform）为准，平台拉取一份只读副本用于授权配置；
    本表不参与登录、不做业务修改，仅由同步接口 upsert。
    """
    __tablename__ = 'synced_users'

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(64), unique=True, nullable=False)  # 认证中心用户ID
    username = db.Column(db.String(64), nullable=False)
    nickname = db.Column(db.String(64), default='')
    nickname_pinyin = db.Column(db.String(128), default='')  # 认证中心解析的完整拼音（搜索用）
    phone = db.Column(db.String(20), default='')
    email = db.Column(db.String(128), default='')
    status = db.Column(db.Integer, default=1)  # 1 启用 0 禁用
    created_at = db.Column(db.DateTime, nullable=True)  # 认证中心侧创建时间
    last_synced_at = db.Column(db.DateTime, default=datetime.now)  # 本地同步时间

    def to_dict(self):
        return {
            'uid': self.uid,
            'username': self.username,
            'nickname': self.nickname or '',
            'nickname_pinyin': self.nickname_pinyin or '',
            'phone': self.phone or '',
            'email': self.email or '',
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'last_synced_at': self.last_synced_at.strftime('%Y-%m-%d %H:%M:%S') if self.last_synced_at else None,
        }


class Menu(db.Model):
    """菜单表：统一菜单与权限来源（替代前端硬编码 menuConfig 与 permissions.PERMISSION_ROWS）。

    - parent_id=NULL：顶层分组（icon 展示在侧边栏）
    - parent_id=分组id：菜单项（path + perm_code 页面权限码）
    - op_codes：该菜单下的操作权限 JSON：[{"code":"op:xxx","label":"..."}]（角色管理勾选用）
    """
    __tablename__ = 'menus'

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, nullable=True, index=True)  # NULL=顶层分组
    name = db.Column(db.String(64), nullable=False)  # 菜单/分组名
    path = db.Column(db.String(128), default='')     # 子菜单路由；分组为空
    icon = db.Column(db.String(16), default='')      # 分组 emoji 图标
    perm_code = db.Column(db.String(64), default='')  # 页面权限码 page:xxx（子菜单）
    op_codes = db.Column(db.Text, default='[]')      # JSON 数组：[{"code":"op:xxx","label":"..."}]
    sort = db.Column(db.Integer, default=0)
    is_builtin = db.Column(db.Boolean, default=True)  # 内置菜单不可删除
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def op_list(self):
        try:
            return json.loads(self.op_codes) if self.op_codes else []
        except (json.JSONDecodeError, TypeError):
            return []

    def to_dict(self):
        return {
            'id': self.id,
            'parent_id': self.parent_id,
            'name': self.name,
            'path': self.path or '',
            'icon': self.icon or '',
            'perm_code': self.perm_code or '',
            'op_codes': self.op_list(),
            'sort': self.sort,
            'is_builtin': self.is_builtin,
            'is_active': self.is_active,
        }


class AuditLog(db.Model):
    """审计日志：平台管理操作轨迹 + 字段级变更（谁/何时/做了什么/结果/差异）"""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    username = db.Column(db.String(64), default='', index=True)  # 冗余用户名（用户删除后仍可追溯）
    module = db.Column(db.String(50), default='')     # 模块：auth/user/role/credential/setting/...
    action = db.Column(db.String(50), default='')     # 动作：login/logout/create/update/delete/...
    method = db.Column(db.String(10), default='')     # HTTP 方法
    path = db.Column(db.String(255), default='')      # 请求路径
    params = db.Column(db.Text, nullable=True)        # 参数 JSON（脱敏）
    detail = db.Column(db.String(500), default='')    # 动作描述（人类可读）
    result = db.Column(db.String(20), default='success', index=True)  # success/failed/denied
    diff = db.Column(db.Text, nullable=True)          # 字段级变更 JSON（old/new）
    ip = db.Column(db.String(64), default='')
    latency_ms = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def to_dict(self):
        import json as _json

        def _load(s):
            try:
                return _json.loads(s) if s else None
            except Exception:
                return s
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'module': self.module,
            'action': self.action,
            'method': self.method,
            'path': self.path,
            'params': _load(self.params),
            'detail': self.detail,
            'result': self.result,
            'diff': _load(self.diff),
            'ip': self.ip,
            'latency_ms': self.latency_ms,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }



class SuperAdmin(db.Model):
    """超级管理员（本地逃生账号）：独立于认证中心用户，仅用于平台管理登录与本地改密。
    users 表只放认证中心同步用户（无本地密码）；超管在此表本地存储，认证中心不可用时仍可登录。"""
    __tablename__ = 'super_admins'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False, default='')
    nickname = db.Column(db.String(80), default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        return bool(self.password_hash) and check_password_hash(self.password_hash, password)

    @property
    def role(self):
        return None

    @property
    def is_super_admin(self):
        return True

    @property
    def auth_source(self):
        return 'local'

    def to_dict(self, include_permissions=False):
        return {
            'id': self.id,
            'username': self.username,
            'nickname': self.nickname or '',
            'role_id': None,
            'role_name': '超级管理员',
            'is_active': self.is_active,
            'is_super_admin': True,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
