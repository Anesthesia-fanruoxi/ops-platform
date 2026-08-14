# -*- coding: utf-8 -*-
"""
菜单接口：当前用户可见菜单树（前端侧边栏数据源，替代硬编码 menuConfig）

菜单与权限的单一来源为 menus 表（bootstrap 种子写入，见 menu_seed.py）。
"""
from flask import g

from core.response import success_response
from modules.system.models import Menu


def list_menus():
    """当前用户可见菜单树（分组/菜单/权限码）。

    - 普通用户：仅返回角色权限（page:xxx）命中的菜单项
    - 超级管理员：逃生最小集——仅 系统管理 组的「用户管理/系统设置」（与历史行为一致）
    """
    user = getattr(g, 'current_user', None)
    is_super = bool(getattr(user, 'is_super_admin', False))
    perms = set()
    if not is_super and user is not None and user.role is not None:
        perms = set(user.role.permissions_list())

    groups = Menu.query.filter_by(parent_id=None, is_active=True).order_by(Menu.sort).all()
    items = Menu.query.filter(Menu.parent_id.isnot(None), Menu.is_active == True).order_by(Menu.sort).all()  # noqa: E712

    tree = []
    for g_ in groups:
        children = []
        for m in items:
            if m.parent_id != g_.id:
                continue
            if is_super:
                # 超管菜单：系统管理分组全部（用户/角色/设置/审计）
                if m.path not in ('/users', '/roles', '/settings', '/audit'):
                    continue
            elif not m.perm_code:
                # 无权限码的菜单项不向普通用户展示（避免泄露未授权入口）
                continue
            elif m.perm_code not in perms:
                continue
            children.append({'path': m.path, 'label': m.name, 'permission': m.perm_code})
        if children:
            tree.append({'key': g_.name, 'icon': g_.icon, 'label': g_.name, 'children': children})
    return success_response(tree)
