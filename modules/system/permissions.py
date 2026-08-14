# -*- coding: utf-8 -*-
"""
权限码与预置角色定义（供角色管理页与初始化种子使用）
"""

# ============================================================
# 权限行定义（角色管理页渲染用，每行 = 一个菜单项 + 关联操作码）
# 新增菜单/权限只需在此维护，前端自动同步
# ============================================================
PERMISSION_ROWS = [
    {'label': '部署平台',     'pageCode': 'page:create',    'opCodes': [{'code': 'op:deploy_project', 'label': '新增项目部署'}, {'code': 'op:deploy_env', 'label': '新增环境部署'}, {'code': 'op:deploy_service', 'label': '新增服务部署'}]},
    {'label': '项目信息',     'pageCode': 'page:projects',  'opCodes': []},
    {'label': '环境信息',     'pageCode': 'page:manage',    'opCodes': [{'code': 'op:recycle', 'label': '回收'}, {'code': 'op:recycle_admin', 'label': '回收站操作'}, {'code': 'op:cicd_build', 'label': '触发构建'}]},
    {'label': '服务信息',     'pageCode': 'page:service_info', 'opCodes': [{'code': 'op:nacos_config_update', 'label': '更新Nacos配置'}]},
    {'label': 'Nginx配置',    'pageCode': 'page:nginx',     'opCodes': [{'code': 'op:nginx_push', 'label': '推送配置'}]},
    {'label': '数据源',       'pageCode': 'page:datasources', 'opCodes': [{'code': 'op:datasource', 'label': '数据源管理'}]},
    {'label': '数据库工具', 'pageCode': 'page:database', 'opCodes': [{'code': 'op:database_fix', 'label': '修复排序'}, {'code': 'op:structure_sync', 'label': '结构同步'}]},
    {'label': 'DDL自动同步', 'pageCode': 'page:ddl_sync', 'opCodes': [{'code': 'op:ddl_sync', 'label': '任务管理'}]},
    {'label': 'CI/CD构建',    'pageCode': 'page:cicd',      'opCodes': [{'code': 'op:cicd_admin', 'label': '配置管理'}]},
    {'label': '系统设置',     'pageCode': 'page:settings',  'opCodes': [{'code': 'op:settings', 'label': '修改设置'}]},
    {'label': '用户管理',     'pageCode': 'page:users',     'opCodes': [{'code': 'op:users', 'label': '管理用户'}]},
    {'label': '角色管理',     'pageCode': 'page:roles',     'opCodes': [{'code': 'op:roles', 'label': '管理角色'}]},
]

# 全部权限码（由 PERMISSION_ROWS 自动派生，保证一致性）
ALL_PERMISSIONS = {
    'page': [{'code': r['pageCode'], 'label': r['label']} for r in PERMISSION_ROWS],
    'op': [],
}
# 操作码去重收集
_seen_ops = set()
for _row in PERMISSION_ROWS:
    for _op in _row['opCodes']:
        if _op['code'] not in _seen_ops:
            _seen_ops.add(_op['code'])
            ALL_PERMISSIONS['op'].append({'code': _op['code'], 'label': _op['label']})

# 预置角色定义
BUILTIN_ROLES = [
    {
        'name': '超级管理员',
        'description': '超级管理员（本地逃生账号）：仅系统管理权限（用户/角色/设置），不可被编辑删除',
        'permissions': ['page:settings', 'op:settings', 'page:users', 'op:users', 'page:roles', 'op:roles'],
        'is_builtin': True,
    },
    {
        'name': '管理员',
        'description': '系统管理员，拥有全部权限',
        'permissions': [p['code'] for group in ALL_PERMISSIONS.values() for p in group],
        'is_builtin': True,
    },
]
