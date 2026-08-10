# -*- coding: utf-8 -*-
"""
数据库初始化：建表 / 字段迁移 / 种子数据

在 create_all 前导入各域模型，确保全部表注册到共享 metadata。
"""
import json
from werkzeug.security import generate_password_hash

from core.db import db
from modules.system.permissions import ALL_PERMISSIONS, BUILTIN_ROLES
from modules.system.models import Role, User, Setting
from modules.system.settings_groups import SETTING_GROUPS, INTERNAL_TYPE, group_of
# 导入以注册表（系统域模型随 modules.system.models 一并注册）
from modules.deploy.models import Project, Environment  # noqa: F401
from modules.nginx.models import NginxConfig  # noqa: F401
from modules.cicd.models import (  # noqa: F401
    GitCredential, DockerfileTemplate, CicdFlowTemplate, BuildAgent, Build
)
from modules.collation.models import CustomDatasource  # noqa: F401


def _get_columns(cursor, table):
    """获取表列名（MySQL information_schema）"""
    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", (table,))
    return [row[0] for row in cursor.fetchall()]


def _add_col_sql(table, col_name, col_type):
    """生成 ADD COLUMN SQL；MySQL 的 TEXT 列不允许带 DEFAULT，旧表补列时移除"""
    if col_type.upper().lstrip().startswith('TEXT'):
        col_type = 'TEXT'
    return f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"


def init_db(app):
    """初始化数据库"""
    db.init_app(app)
    with app.app_context():
        db.create_all()

        # 自动迁移：为 environments 表添加缺失字段
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'environments')
            if 'is_deleted' not in columns:
                cursor.execute("ALTER TABLE environments ADD COLUMN is_deleted BOOLEAN DEFAULT 0")
                conn.commit()
            if 'deleted_at' not in columns:
                cursor.execute("ALTER TABLE environments ADD COLUMN deleted_at DATETIME")
                conn.commit()
            if 'recycle_info' not in columns:
                cursor.execute("ALTER TABLE environments ADD COLUMN recycle_info TEXT")
                conn.commit()
            if 'deploy_config' not in columns:
                cursor.execute("ALTER TABLE environments ADD COLUMN deploy_config TEXT")
                conn.commit()
            if 'nacos_namespace' not in columns:
                cursor.execute(_add_col_sql('environments', 'nacos_namespace', "TEXT DEFAULT ''"))
                conn.commit()
            if 'seata_nacos_namespace' not in columns:
                cursor.execute(_add_col_sql('environments', 'seata_nacos_namespace', "TEXT DEFAULT ''"))
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：为 cicd_builds 表添加缺失字段
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'cicd_builds')
            if columns and 'cancel_requested' not in columns:
                cursor.execute("ALTER TABLE cicd_builds ADD COLUMN cancel_requested BOOLEAN DEFAULT 0")
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：为 cicd_flow_templates 表添加多步骤流程字段
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'cicd_flow_templates')
            tpl_cols = [
                ('language', "VARCHAR(30) DEFAULT 'java'"),
                ('git_docker_image', "VARCHAR(200) DEFAULT ''"),
                ('build_docker_image', "VARCHAR(200) DEFAULT ''"),
                ('artifact_dirs', "TEXT DEFAULT ''"),
                ('artifact_dir', "VARCHAR(200) DEFAULT ''"),
            ]
            if columns:
                for col_name, col_type in tpl_cols:
                    if col_name not in columns:
                        cursor.execute(_add_col_sql('cicd_flow_templates', col_name, col_type))
                        conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：为 cicd_builds 表添加多步骤快照字段
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'cicd_builds')
            build_cols = [
                ('project_type', "VARCHAR(20) DEFAULT 'backend'"),
                ('language', "VARCHAR(30) DEFAULT ''"),
                ('steps_snapshot', "TEXT DEFAULT ''"),
            ]
            if columns:
                for col_name, col_type in build_cols:
                    if col_name not in columns:
                        cursor.execute(_add_col_sql('cicd_builds', col_name, col_type))
                        conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：为 cicd_credentials 表添加 url 字段（harbor 类型用）
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'cicd_credentials')
            if columns and 'url' not in columns:
                cursor.execute("ALTER TABLE cicd_credentials ADD COLUMN url VARCHAR(200) DEFAULT ''")
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：为 users 表添加昵称/统一鉴权字段
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'users')
            if columns and 'nickname' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN nickname VARCHAR(80) DEFAULT ''")
                conn.commit()
            if columns and 'auth_source' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN auth_source VARCHAR(16) DEFAULT 'local'")
                conn.commit()
            if columns and 'auth_uid' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN auth_uid VARCHAR(64) DEFAULT NULL")
                conn.commit()
                try:
                    cursor.execute("ALTER TABLE users ADD UNIQUE INDEX uq_users_auth_uid (auth_uid)")
                    conn.commit()
                except Exception:
                    pass  # 索引已存在
            if columns and 'phone' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20) DEFAULT ''")
                conn.commit()
            if columns and 'email' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN email VARCHAR(128) DEFAULT ''")
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：synced_users 表补充手机号/邮箱列（表不存在则跳过）
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            scols = _get_columns(cursor, 'synced_users')
            if scols and 'phone' not in scols:
                cursor.execute("ALTER TABLE synced_users ADD COLUMN phone VARCHAR(20) DEFAULT ''")
                conn.commit()
            if scols and 'email' not in scols:
                cursor.execute("ALTER TABLE synced_users ADD COLUMN email VARCHAR(128) DEFAULT ''")
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：settings 表添加 type 列（deploy/nginx/middleware/internal）并按 key 回填
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'settings')
            if columns and 'type' not in columns:
                cursor.execute(_add_col_sql('settings', 'type', "VARCHAR(20) DEFAULT 'deploy'"))
                conn.commit()
                all_keys = []
                for group, keys in SETTING_GROUPS.items():
                    all_keys.extend(keys)
                    ph = ', '.join(['%s'] * len(keys))
                    cursor.execute(
                        f"UPDATE settings SET type='{group}' WHERE `key` IN ({ph})",
                        keys,
                    )
                    conn.commit()
                ph = ', '.join(['%s'] * len(all_keys))
                cursor.execute(
                    f"UPDATE settings SET type='{INTERNAL_TYPE}' WHERE `key` NOT IN ({ph})",
                    all_keys,
                )
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 初始化预置角色
        for role_def in BUILTIN_ROLES:
            if not Role.query.filter_by(name=role_def['name']).first():
                db.session.add(Role(
                    name=role_def['name'],
                    description=role_def['description'],
                    permissions=json.dumps(role_def['permissions'], ensure_ascii=False),
                    is_builtin=role_def.get('is_builtin', False),
                ))
        db.session.commit()

        # 管理员角色权限自动补全：新增权限码发布后自动并入（保证“拥有全部权限”）
        admin_role = Role.query.filter_by(name='管理员', is_builtin=True).first()
        if admin_role:
            all_codes = [p['code'] for group in ALL_PERMISSIONS.values() for p in group]
            current = admin_role.permissions_list()
            missing = [c for c in all_codes if c not in current]
            if missing:
                admin_role.permissions = json.dumps(current + missing, ensure_ascii=False)
                db.session.commit()

        # 初始化默认管理员账号（关联“管理员”角色）
        # 内置角色（含「超级管理员」）已由 BUILTIN_ROLES 循环创建；默认 admin 即超级管理员
        super_role = Role.query.filter_by(name='超级管理员').first()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                role_id=super_role.id if super_role else None,
                is_active=True,
            ))
            db.session.commit()

        # 超级管理员初始化（角色驱动）：无「超级管理员」角色用户时，按环境变量（默认 admin）指定
        # - 环境变量 SUPER_ADMIN_USERNAME / SUPER_ADMIN_PASSWORD 可指定账号（新部署用，避免默认 admin 易猜）
        # - 未指定则默认 admin（存量部署自动把 admin 提升为超级管理员角色）
        import os as _os
        if super_role and not User.query.filter_by(role_id=super_role.id).first():
            super_name = (_os.getenv('SUPER_ADMIN_USERNAME') or 'admin').strip().lower()
            super_pass = _os.getenv('SUPER_ADMIN_PASSWORD') or 'admin123'
            super_user = User.query.filter_by(username=super_name).first()
            if super_user:
                super_user.role_id = super_role.id
                super_user.auth_source = 'local'
                if _os.getenv('SUPER_ADMIN_PASSWORD'):
                    super_user.password_hash = generate_password_hash(super_pass)
                # 角色变更后清旧会话（权限快照残留），强制重新登录
                from modules.system.session_cache import delete_user_sessions
                delete_user_sessions(super_user.id)
            else:
                db.session.add(User(
                    username=super_name,
                    password_hash=generate_password_hash(super_pass),
                    role_id=super_role.id,
                    is_active=True,
                    auth_source='local',
                ))
            db.session.commit()
            if super_pass == 'admin123' and not _os.getenv('SUPER_ADMIN_PASSWORD'):
                print(f'[bootstrap] 超级管理员: {super_name}（默认密码 admin123，请登录后尽快修改）')
            else:
                print(f'[bootstrap] 超级管理员已就绪: {super_name}')

        # 旧版超管列迁移：is_super_admin=1 的用户 → 「超级管理员」角色 → 删除列与索引
        # （改为角色驱动后不再需要该列；迁移后清受影响用户会话，防止旧全权限会话残留）
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            cols = _get_columns(cursor, 'users')
            if cols and 'is_super_admin' in cols and super_role:
                cursor.execute(
                    "UPDATE users SET role_id=%s WHERE is_super_admin=1 AND (role_id IS NULL OR role_id=0)",
                    (super_role.id,))
                conn.commit()
                cursor.execute("SELECT id FROM users WHERE is_super_admin=1")
                for (uid_,) in cursor.fetchall():
                    from modules.system.session_cache import delete_user_sessions
                    delete_user_sessions(uid_)
                try:
                    cursor.execute("DROP INDEX uq_users_super_admin ON users")
                    conn.commit()
                except Exception:
                    pass
                cursor.execute("ALTER TABLE users DROP COLUMN is_super_admin")
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 初始化默认设置
        defaults = [
            {'key': 'yaml_output_dir', 'value': './output', 'description': 'YAML文件输出目录'},
            {'key': 'yaml_recycle_dir', 'value': './recycle', 'description': 'YAML回收目录'},
            {'key': 'nfs_server', 'value': '172.16.0.13', 'description': 'NFS服务器地址（SSH访问用）'},
            {'key': 'nfs_cluster_server', 'value': '172.16.0.13', 'description': 'NFS集群内网地址（YAML中Pod挂载用）'},
            {'key': 'nfs_ssh_port', 'value': '22', 'description': 'NFS SSH端口'},
            {'key': 'nfs_ssh_user', 'value': 'root', 'description': 'NFS SSH用户名'},
            {'key': 'nfs_ssh_pass', 'value': '', 'description': 'NFS SSH密码'},
            {'key': 'nfs_logs_mount', 'value': '/data/logs', 'description': 'NFS日志挂载目录'},
            {'key': 'nfs_data_mount', 'value': '/data/project', 'description': 'NFS数据挂载目录'},
            {'key': 'nfs_datastorg_mount', 'value': '/data/project/datastorg', 'description': 'NFS存储挂载目录'},
            {'key': 'harbor_url', 'value': 'hub.hzbxhd.com', 'description': 'Harbor地址（域名，无需 https://）'},
            {'key': 'harbor_user', 'value': 'admin', 'description': 'Harbor用户名'},
            {'key': 'harbor_pass', 'value': '', 'description': 'Harbor密码'},
            {'key': 'harbor_cleanup_keep_versions', 'value': '3', 'description': 'Harbor镜像保留版本数'},
            {'key': 'harbor_cleanup_cron', 'value': '0 0 * * * *', 'description': 'Harbor清理调度Cron'},
            {'key': 'default_domain', 'value': 'hzbxhd.com', 'description': '默认域名后缀'},
            {'key': 'default_publicurl', 'value': 'public.hzbxhd.com', 'description': 'PublicURL'},
            {'key': 'default_privateurl', 'value': 'private.hzbxhd.com', 'description': 'PrivateURL'},
            {'key': 'default_publicbucket', 'value': 'bxhd-public', 'description': 'Public Bucket'},
            {'key': 'default_privatebucket', 'value': 'bxhd-private', 'description': 'Private Bucket'},
            {'key': 'default_ossak', 'value': 'ASGe9AUbO03LBmuKM_5WggceBTRmV75XOSwVxJ21', 'description': 'OSS Access Key'},
            {'key': 'default_osssk', 'value': 'osCQxXGFkpYxNl5OfvTkyqDqgHgNBKt3qUDQbwXF', 'description': 'OSS Secret Key'},
            {'key': 'default_encrypted', 'value': 'i5t9zs843tpPYsXgP0ptE0z73HHLTdKMHdbUcxGYCyWQG0YhzvyM7nL5xuJz27im', 'description': '加密盐'},
            {'key': 'default_riskKey', 'value': 'fasssdgsddd', 'description': '风控加密盐'},
            {'key': 'default_es_pass', 'value': '76wq19gr17vBh8Q4AE6C8FDC', 'description': 'ES密码'},
            {'key': 'default_nacos_namespace', 'value': '', 'description': '默认Nacos命名空间ID'},
            {'key': 'k8s_master_ip', 'value': '', 'description': 'K8s Master地址（NodeIP，SSH访问用）'},
            {'key': 'k8s_cluster_ip', 'value': '', 'description': 'K8s集群内网地址（Nginx反代/Pod访问用）'},
            {'key': 'k8s_ssh_user', 'value': 'root', 'description': 'K8s Master SSH用户名'},
            {'key': 'k8s_ssh_pass', 'value': '', 'description': 'K8s Master SSH密码'},
            {'key': 'k8s_yaml_remote_dir', 'value': '/data/yaml', 'description': 'K8s Master远程YAML存放目录'},
            {'key': 'k8s_yaml_remote_recycle_dir', 'value': '/data/yaml-recycle', 'description': 'K8s Master远程YAML回收目录'},
            {'key': 'ignored_projects', 'value': '', 'description': '忽略的项目列表（英文逗号分隔）'},
            {'key': 'nginx_server', 'value': '', 'description': 'Nginx服务器地址'},
            {'key': 'nginx_ssh_port', 'value': '22', 'description': 'Nginx SSH端口'},
            {'key': 'nginx_ssh_user', 'value': 'root', 'description': 'Nginx SSH用户名'},
            {'key': 'nginx_ssh_pass', 'value': '', 'description': 'Nginx SSH密码'},
            {'key': 'nginx_remote_dir', 'value': '/etc/nginx/conf.d', 'description': 'Nginx远程配置目录'},
            {'key': 'nginx_local_dir', 'value': './nginx_configs', 'description': 'Nginx本地存储目录'},
            {'key': 'mysql_default_user', 'value': 'root', 'description': 'MySQL默认用户名（测试环境通用）'},
            {'key': 'mysql_default_pass', 'value': '', 'description': 'MySQL默认密码（测试环境通用）'},
            {'key': 'redis_user', 'value': '', 'description': 'Redis用户名（非必填）'},
            {'key': 'redis_pass', 'value': '', 'description': 'Redis密码'},
            {'key': 'rabbitmq_user', 'value': 'admin', 'description': 'RabbitMQ用户名'},
            {'key': 'rabbitmq_pass', 'value': '', 'description': 'RabbitMQ密码'},
            {'key': 'nacos_user', 'value': 'nacos', 'description': 'Nacos用户名'},
            {'key': 'nacos_pass', 'value': '', 'description': 'Nacos密码'},
            {'key': 'token_expire_hours', 'value': '8', 'description': 'Token过期时间（小时），请求时滑动续期'},
            {'key': 'password_min_length', 'value': '6', 'description': '密码最小长度'},
            {'key': 'password_require_upper', 'value': '0', 'description': '密码是否必须包含大写字母（0/1）'},
            {'key': 'password_require_digit', 'value': '0', 'description': '密码是否必须包含数字（0/1）'},
            {'key': 'authplatform_base_url', 'value': '', 'description': '统一鉴权中心地址（如 http://127.0.0.1:8080），留空=使用本地账号登录'},
            {'key': 'authplatform_platform_id', 'value': '', 'description': '统一鉴权中心平台标识（如 ops-platform），在鉴权中心后台注册'},
            {'key': 'authplatform_secret', 'value': '', 'description': '统一鉴权中心平台加密盐（仅创建时展示一次，用于请求签名）'},
        ]
        for item in defaults:
            if not Setting.query.filter_by(key=item['key']).first():
                db.session.add(Setting(type=group_of(item['key']), **item))
        db.session.commit()

        # Agent 通讯共享密钥（首次生成随机值，所有 Agent 共用）
        if not Setting.query.filter_by(key='agent_comm_secret').first():
            import secrets as _secrets
            db.session.add(Setting(
                key='agent_comm_secret',
                value=_secrets.token_hex(32),
                description='Agent通讯共享密钥（AES-GCM加密，所有Agent共用）',
                type=group_of('agent_comm_secret'),
            ))
            db.session.commit()
