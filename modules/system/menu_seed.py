# -*- coding: utf-8 -*-
"""
菜单种子数据（menus 表初始化，幂等：仅当表为空时插入）

菜单与权限的单一来源——前端侧边栏菜单（GET /api/menus）与角色管理权限行
（GET /api/roles/permissions）均由此派生；后端权限码（page:/op:）也由 menus 表汇总校验。
"""
import json

from core.db import db
from modules.system.models import Menu

# 分组：(name, 图标)
MENU_GROUPS = [
    ('部署平台', '🚀'),
    ('项目管理', '📋'),
    ('Nginx', '🌐'),
    ('MySQL', '🗄️'),
    ('CI/CD', '🔧'),
    ('系统管理', '⚙️'),
]

# 菜单项：(分组名, 菜单名, 路径, page码, [(op码, op标签), ...])
# 注意：权限码与前端路由/后端接口保持一致（page:database 为数据库工具新码，
# 旧 page:collation/op:collation_fix 已废弃；/database 为新路由，旧 /collation 已删除）
MENU_ITEMS = [
    ('部署平台', '新增项目', '/create/project', 'page:create', [('op:deploy_project', '新增项目部署')]),
    ('部署平台', '新增环境', '/create/env', 'page:create', [('op:deploy_env', '新增环境部署')]),
    ('部署平台', '新增服务', '/create/service', 'page:create', [('op:deploy_service', '新增服务部署')]),
    ('项目管理', '项目信息', '/projects', 'page:projects', []),
    ('项目管理', '环境信息', '/manage', 'page:manage', [('op:recycle', '回收'), ('op:recycle_admin', '回收站操作'), ('op:cicd_build', '触发构建')]),
    ('项目管理', '服务信息', '/services', 'page:service_info', [('op:nacos_config_update', '更新Nacos配置')]),
    ('Nginx', 'Nginx配置', '/nginx', 'page:nginx', [('op:nginx_push', '推送配置')]),
    ('MySQL', '数据源', '/datasources', 'page:datasources', [('op:datasource', '数据源管理')]),
    ('MySQL', '字符集排序修正', '/database', 'page:database', [('op:database_fix', '修复排序')]),
    ('MySQL', '表结构对比同步', '/schema', 'page:schema', [('op:structure_sync', '结构同步')]),
    ('MySQL', 'DDL自动同步', '/ddl-sync', 'page:ddl_sync', [('op:ddl_sync', '任务管理')]),
    ('CI/CD', 'CI/CD管理', '/cicd', 'page:cicd', [('op:cicd_admin', '配置管理')]),
    ('CI/CD', '调度中心', '/schedule', 'page:cicd_schedule', [('op:agent', 'Agent管理')]),
    ('系统管理', '用户管理', '/users', 'page:users', [('op:users', '管理用户')]),
    ('系统管理', '角色管理', '/roles', 'page:roles', [('op:roles', '管理角色')]),
    ('系统管理', '系统设置', '/settings', 'page:settings', [('op:settings', '修改设置')]),
    ('系统管理', '审计日志', '/audit', 'page:audit', []),
]


def seed_menus():
    """内置菜单全量对齐（幂等自愈，可重复调用）：

    - 分组按 name upsert，菜单项按「分组+path」upsert（更新名称/权限码/op码/排序）
    - 删除 seed 之外的**内置**菜单项（旧路径/旧权限码自动清理，如 /collation、page:collation）
    - 自定义菜单（is_builtin=False）不受影响
    """
    seed_group_ids = {}
    for i, (gname, icon) in enumerate(MENU_GROUPS):
        g = Menu.query.filter_by(parent_id=None, name=gname).first()
        if g is None:
            g = Menu(parent_id=None, name=gname, icon=icon, sort=i, is_builtin=True, is_active=True)
            db.session.add(g)
            db.session.flush()  # 取分组 id
        else:
            g.icon = icon
            g.sort = i
        seed_group_ids[gname] = g.id

    seed_paths = set()
    for j, (gname, mname, path, perm_code, ops) in enumerate(MENU_ITEMS):
        seed_paths.add(path)
        op_json = json.dumps([{'code': c, 'label': l} for c, l in ops], ensure_ascii=False)
        m = Menu.query.filter_by(parent_id=seed_group_ids[gname], path=path).first()
        if m is None:
            db.session.add(Menu(
                parent_id=seed_group_ids[gname], name=mname, path=path,
                perm_code=perm_code, op_codes=op_json, sort=j, is_builtin=True, is_active=True,
            ))
        else:
            m.name = mname
            m.perm_code = perm_code
            m.op_codes = op_json
            m.sort = j
            m.is_builtin = True

    # 清理 seed 之外的内置菜单项（旧码/旧路径自愈）
    builtin_group_ids = set(seed_group_ids.values())
    for m in Menu.query.filter(Menu.is_builtin == True, Menu.parent_id.isnot(None)).all():  # noqa: E712
        if m.parent_id in builtin_group_ids and m.path not in seed_paths:
            db.session.delete(m)

    db.session.commit()
