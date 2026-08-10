# -*- coding: utf-8 -*-
"""
角色管理接口处理函数
"""
import json
from flask import request, g
from core.db import db
from modules.system.models import Role
from modules.system.permissions import ALL_PERMISSIONS, PERMISSION_ROWS
from core.response import success_response, error_response
from core.security import require_permission


def _get_user_permissions():
    """从 g.current_user 获取权限码列表"""
    user = getattr(g, 'current_user', None)
    if user and user.role:
        return user.role.permissions_list()
    return []


@require_permission('page:roles')
def list_roles():
    """获取所有角色列表（超级管理员为内置角色，不可修改，不返回）"""
    roles = Role.query.filter(Role.name != '超级管理员').order_by(Role.id.asc()).all()
    return success_response([r.to_dict() for r in roles])


@require_permission('page:roles')
def role_detail(role_id):
    """获取角色详情"""
    role = Role.query.get(role_id)
    if not role:
        return error_response('角色不存在', 404)
    return success_response(role.to_dict())


@require_permission('op:roles')
def create_role():
    """
    创建角色
    请求体: {"name": "...", "description": "...", "permissions": ["page:create", "op:deploy", ...]}
    """
    data = request.json or {}
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    permissions = data.get('permissions', [])

    if not name:
        return error_response('角色名称不能为空', 400)

    if Role.query.filter_by(name=name).first():
        return error_response(f'角色名称「{name}」已存在', 400)

    # 验证权限码合法性
    all_valid_codes = {p['code'] for group in ALL_PERMISSIONS.values() for p in group}
    invalid = [p for p in permissions if p not in all_valid_codes]
    if invalid:
        return error_response(f'无效的权限码: {", ".join(invalid)}', 400)

    role = Role(
        name=name,
        description=description,
        permissions=json.dumps(permissions, ensure_ascii=False),
        is_builtin=False,
    )
    db.session.add(role)
    db.session.commit()
    return success_response(role.to_dict(), '角色创建成功')


@require_permission('op:roles')
def update_role(role_id):
    """
    更新角色
    请求体: {"name": "...", "description": "...", "permissions": [...]}
    """
    role = Role.query.get(role_id)
    if not role:
        return error_response('角色不存在', 404)
    if role.is_builtin:
        return error_response(f'内置角色「{role.name}」不可编辑（防止提权篡改）', 400)

    data = request.json or {}
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    permissions = data.get('permissions', [])

    if not name:
        return error_response('角色名称不能为空', 400)

    # 检查名称唯一性（排除自身）
    existing = Role.query.filter(Role.name == name, Role.id != role_id).first()
    if existing:
        return error_response(f'角色名称「{name}」已存在', 400)

    # 验证权限码
    all_valid_codes = {p['code'] for group in ALL_PERMISSIONS.values() for p in group}
    invalid = [p for p in permissions if p not in all_valid_codes]
    if invalid:
        return error_response(f'无效的权限码: {", ".join(invalid)}', 400)

    role.name = name
    role.description = description
    role.permissions = json.dumps(permissions, ensure_ascii=False)
    db.session.commit()
    # 角色权限变更即时生效：每次请求实时校验会读取最新权限，无需清会话/重新登录
    return success_response(role.to_dict(), '角色更新成功')


@require_permission('op:roles')
def delete_role(role_id):
    """删除角色（内置角色不可删除）"""
    role = Role.query.get(role_id)
    if not role:
        return error_response('角色不存在', 404)

    if role.is_builtin:
        return error_response(f'内置角色「{role.name}」不可删除', 400)

    # 检查是否有用户关联
    if role.users and len(role.users) > 0:
        return error_response(f'角色「{role.name}」下还有 {len(role.users)} 个用户，请先移除', 400)

    db.session.delete(role)
    db.session.commit()
    return success_response(msg='角色删除成功')


@require_permission('page:roles')
def list_permissions():
    """获取全部可用权限码 + 权限行结构（供角色编辑页动态渲染）"""
    return success_response({
        'rows': PERMISSION_ROWS,
        'all': ALL_PERMISSIONS,
    })
