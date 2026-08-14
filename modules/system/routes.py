# -*- coding: utf-8 -*-
"""
系统管理域路由注册：auth / users / roles / settings
"""
from flask import Blueprint

from modules.system.auth_api import login, login_2fa, admin_login, logout, me, change_password, health_check
from modules.system.monitor_api import monitor_stream
from modules.system.user_api import (
    list_users, create_user, update_user, delete_user, reset_password,
    sync_users_from_auth, list_synced_users, update_profile_from_auth, totp_setup,
)
from modules.system.role_api import (
    list_roles, role_detail, create_role,
    update_role, delete_role, list_permissions
)
from modules.system.settings_api import (
    list_settings, update_settings, debug_settings,
    test_ssh, test_k8s_ssh, test_nginx_ssh, test_harbor
)
from modules.system.menu_api import list_menus

# ── 认证 ──
auth_bp = Blueprint('auth', __name__)
auth_bp.add_url_rule('/login', 'login', login, methods=['POST'])
auth_bp.add_url_rule('/login-2fa', 'login_2fa', login_2fa, methods=['POST'])
auth_bp.add_url_rule('/admin-login', 'admin_login', admin_login, methods=['POST'])
auth_bp.add_url_rule('/logout', 'logout', logout, methods=['POST'])
auth_bp.add_url_rule('/me', 'me', me, methods=['GET'])
auth_bp.add_url_rule('/change-password', 'change_password', change_password, methods=['POST'])

# ── 用户管理 ──
users_bp = Blueprint('users', __name__)
users_bp.add_url_rule('/list', 'list_users', list_users, methods=['GET'])
users_bp.add_url_rule('/create', 'create_user', create_user, methods=['POST'])
users_bp.add_url_rule('/update/<int:user_id>', 'update_user', update_user, methods=['POST'])
users_bp.add_url_rule('/delete/<int:user_id>', 'delete_user', delete_user, methods=['POST'])
users_bp.add_url_rule('/reset-password/<int:user_id>', 'reset_password', reset_password, methods=['POST'])
users_bp.add_url_rule('/sync', 'sync_users_from_auth', sync_users_from_auth, methods=['POST'])
users_bp.add_url_rule('/synced', 'list_synced_users', list_synced_users, methods=['GET'])
users_bp.add_url_rule('/profile/<int:user_id>', 'update_profile_from_auth', update_profile_from_auth, methods=['POST'])
users_bp.add_url_rule('/totp-setup/<int:user_id>', 'totp_setup', totp_setup, methods=['POST'])

# ── 角色管理 ──
roles_bp = Blueprint('roles', __name__)
roles_bp.add_url_rule('/list', 'list_roles', list_roles, methods=['GET'])
roles_bp.add_url_rule('/detail/<int:role_id>', 'role_detail', role_detail, methods=['GET'])
roles_bp.add_url_rule('/create', 'create_role', create_role, methods=['POST'])
roles_bp.add_url_rule('/update/<int:role_id>', 'update_role', update_role, methods=['POST'])
roles_bp.add_url_rule('/delete/<int:role_id>', 'delete_role', delete_role, methods=['POST'])
roles_bp.add_url_rule('/permissions', 'list_permissions', list_permissions, methods=['GET'])

# ── 系统设置 ──
settings_bp = Blueprint('settings', __name__)
settings_bp.add_url_rule('/list', 'list_settings', list_settings, methods=['GET'])

# 首页概况统计（登录即可见）
from modules.system.dashboard_api import dashboard_stats
dashboard_bp = Blueprint('dashboard', __name__)
dashboard_bp.add_url_rule('/stats', 'dashboard_stats', dashboard_stats, methods=['GET'])
from modules.system.monitor_api import dashboard_monitor_health, dashboard_monitor_check
dashboard_bp.add_url_rule('/monitor/health', 'dashboard_monitor_health', dashboard_monitor_health, methods=['GET'])
dashboard_bp.add_url_rule('/monitor/<check_key>', 'dashboard_monitor_check', dashboard_monitor_check, methods=['GET'])
settings_bp.add_url_rule('/update', 'update_settings', update_settings, methods=['POST'])
settings_bp.add_url_rule('/debug', 'debug_settings', debug_settings, methods=['GET'])
settings_bp.add_url_rule('/test-ssh', 'test_ssh', test_ssh, methods=['POST'])
settings_bp.add_url_rule('/test-k8s-ssh', 'test_k8s_ssh', test_k8s_ssh, methods=['POST'])
settings_bp.add_url_rule('/test-nginx-ssh', 'test_nginx_ssh', test_nginx_ssh, methods=['POST'])
settings_bp.add_url_rule('/test-harbor', 'test_harbor', test_harbor, methods=['POST'])


# ── 菜单（前端侧边栏数据源，来自 menus 表） ──
menus_bp = Blueprint('menus', __name__)
menus_bp.add_url_rule('', 'list_menus', list_menus, methods=['GET'])


# ── 审计日志（page:audit 权限） ──
from modules.system.audit_api import list_audit_logs, audit_modules
audit_bp = Blueprint('audit', __name__)
audit_bp.add_url_rule('/list', 'list_audit_logs', list_audit_logs, methods=['GET'])
audit_bp.add_url_rule('/modules', 'audit_modules', audit_modules, methods=['GET'])


# ── 首页动态数据（SSE 实时健康检查，登录即可；归入 dashboard 域供首页/后续动态数据复用） ──
monitor_bp = Blueprint('monitor', __name__)
monitor_bp.add_url_rule('/stream', 'monitor_stream', monitor_stream, methods=['GET'])


def register(app):
    """注册系统管理域蓝图"""
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(roles_bp, url_prefix='/api/roles')
    app.register_blueprint(settings_bp, url_prefix='/api/settings')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(menus_bp, url_prefix='/api/menus')
    app.register_blueprint(audit_bp, url_prefix='/api/audit')
    app.register_blueprint(monitor_bp, url_prefix='/api/dashboard')
    # 健康检查不再公开探测（改为系统管理 → 监控信息，SSE 实时展示）
