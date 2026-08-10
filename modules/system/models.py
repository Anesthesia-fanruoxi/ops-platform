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
    permissions = db.Column(db.Text, default='[]')  # JSON数组，如 ["page:create","op:deploy"]
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
            'phone': self.phone or '',
            'email': self.email or '',
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'last_synced_at': self.last_synced_at.strftime('%Y-%m-%d %H:%M:%S') if self.last_synced_at else None,
        }
