# -*- coding: utf-8 -*-
"""
角色管理接口处理函数
"""
import json
from flask import request, g
from core.db import db
from core.audit import record_audit_diff
from modules.system.models import Role
from modules.system.permissions import BUILTIN_ROLES
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
    请求体: {"name": "...", "description": "...", "permissions": ["page:create", "op:deploy_project", ...]}
    """
    data = request.json or {}
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    permissions = data.get('permissions', [])

    if not name:
        return error_response('角色名称不能为空', 400)

    if Role.query.filter_by(name=name).first():
        return error_response(f'角色名称「{name}」已存在', 400)

    # 验证权限码合法性（来源：menus 表单一来源）
    all_valid_codes = _menu_valid_codes()
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
    data = request.json or {}
    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    permissions = data.get('permissions', [])
    if role.is_builtin and name and name != role.name:
        return error_response('内置角色不可改名', 400)
    _old_snap = {'name': role.name, 'description': role.description,
                 'permissions': json.loads(role.permissions or '[]')}

    if not name:
        return error_response('角色名称不能为空', 400)

    # 检查名称唯一性（排除自身）
    existing = Role.query.filter(Role.name == name, Role.id != role_id).first()
    if existing:
        return error_response(f'角色名称「{name}」已存在', 400)

    # 验证权限码
    all_valid_codes = _menu_valid_codes()
    invalid = [p for p in permissions if p not in all_valid_codes]
    if invalid:
        return error_response(f'无效的权限码: {", ".join(invalid)}', 400)

    role.name = name
    role.description = description
    role.permissions = json.dumps(permissions, ensure_ascii=False)
    db.session.commit()
    _new_snap = {'name': role.name, 'description': role.description, 'permissions': permissions}
    record_audit_diff('role', 'update', role.id, _old_snap, _new_snap)
    # 角色权限变更即时生效：每次请求实时校验会读取最新权限，无需清会话/重新登录
    return success_response(role.to_dict(), '角色更新成功')


@require_permission('op:roles')
def delete_role(role_id):
    """删除角色（超级管理员角色除外）"""
    role = Role.query.get(role_id)
    if not role:
        return error_response('角色不存在', 404)

    if role.name == '超级管理员':
        return error_response('超级管理员角色不可删除（逃生通道）', 400)

    # 检查是否有用户关联
    if role.users and len(role.users) > 0:
        return error_response(f'角色「{role.name}」下还有 {len(role.users)} 个用户，请先移除', 400)

    db.session.delete(role)
    db.session.commit()
    return success_response(msg='角色删除成功')


def _menu_valid_codes():
    """全部合法权限码（page + op），来源：menus 表（菜单与权限单一来源）"""
    from modules.system.models import Menu
    codes = set()
    for m in Menu.query.all():
        if m.perm_code:
            codes.add(m.perm_code)
        for op in m.op_list():
            codes.add(op['code'])
    return codes


@require_permission('page:roles')
def list_permissions():
    """获取权限树结构（角色编辑页渲染用；来源：menus 表——分组 → 菜单项 → 操作码）"""
    from modules.system.models import Menu
    groups = Menu.query.filter_by(parent_id=None).order_by(Menu.sort).all()
    items = Menu.query.filter(Menu.parent_id.isnot(None), Menu.perm_code != '').order_by(Menu.sort).all()
    tree = []
    for g in groups:
        children = []
        for m in items:
            if m.parent_id != g.id:
                continue
            children.append({'label': m.name, 'pageCode': m.perm_code, 'opCodes': m.op_list()})
        if children:
            tree.append({'name': g.name, 'children': children})
    return success_response({'rows': tree, 'all': {'page': [], 'op': []}})
