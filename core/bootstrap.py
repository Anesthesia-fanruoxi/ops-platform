# -*- coding: utf-8 -*-
"""
数据库初始化：建表 / 字段迁移 / 种子数据

在 create_all 前导入各域模型，确保全部表注册到共享 metadata。
"""
import json
from werkzeug.security import generate_password_hash
from sqlalchemy import text

from core.db import db
from modules.system.permissions import BUILTIN_ROLES
from modules.system.models import Role, User, Setting
from modules.system.settings_groups import SETTING_GROUPS, INTERNAL_TYPE, group_of
# 导入以注册表（系统域模型随 modules.system.models 一并注册）
from modules.deploy.models import Project, Environment  # noqa: F401
from modules.nginx.models import NginxConfig  # noqa: F401
from modules.cicd.models import (  # noqa: F401
    GitCredential, DockerfileTemplate, CicdFlowTemplate, BuildAgent, Build
)
from modules.database.models import CustomDatasource  # noqa: F401


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

        # 菜单种子（对齐式 upsert：菜单是前端侧边栏与角色管理权限行的单一来源）
        try:
            from modules.system.menu_seed import seed_menus
            seed_menus()
        except Exception as e:  # 菜单失败影响角色管理可用性，需告警而非静默
            import logging
            logging.getLogger('bootstrap').error('menus 表种子初始化失败: %s', e)

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

        # 自动迁移：cicd_flow_templates 删除顶层冗余列（configs 已接管；迁移前回填空 configs）
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'cicd_flow_templates')
            if columns:
                drop_cols = ['language', 'git_docker_image', 'git_url', 'git_credential_id',
                             'build_docker_image', 'build_command', 'artifact_dirs', 'artifact_dir',
                             'dockerfile_template_id', 'image_name']
                existing = [c for c in drop_cols if c in columns]
                if existing:
                    # 回填：configs 为空的行从顶层字段生成（防数据丢失）
                    cursor.execute(
                        "SELECT id, project_type, configs, language, git_credential_id, "
                        "build_docker_image, artifact_dirs, artifact_dir, dockerfile_template_id "
                        "FROM cicd_flow_templates"
                    )
                    import json as _json
                    for row in cursor.fetchall():
                        rid, ptype, cfg_text = row[0], row[1] or 'backend', row[2]
                        try:
                            if cfg_text and _json.loads(cfg_text):
                                continue
                        except Exception:
                            pass
                        be = {
                            'language': row[3] or 'java', 'git_url': '',
                            'git_credential_id': row[4], 'build_docker_image': row[5] or '',
                            'build_command': '', 'artifact_dirs': row[6] or '',
                            'artifact_dir': row[7] or '', 'dockerfile_template_id': row[8],
                        }
                        cfg = {
                            'backend': be,
                            'frontend': {'language': 'vue', 'git_url': '', 'git_credential_id': None,
                                         'build_docker_image': '', 'build_command': '', 'artifact_dirs': '',
                                         'artifact_dir': 'dist', 'dockerfile_template_id': None},
                        }
                        cursor.execute("UPDATE cicd_flow_templates SET configs=%s WHERE id=%s",
                                       (_json.dumps(cfg, ensure_ascii=False), rid))
                    conn.commit()
                    # 先删除引用待删列的外键约束（FK 列无法直接 DROP COLUMN）
                    cursor.execute(
                        "SELECT CONSTRAINT_NAME, COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='cicd_flow_templates' "
                        "AND REFERENCED_TABLE_NAME IS NOT NULL"
                    )
                    for fk, colname in cursor.fetchall():
                        if colname in drop_cols:
                            cursor.execute(f"ALTER TABLE cicd_flow_templates DROP FOREIGN KEY {fk}")
                    conn.commit()
                    for col in existing:
                        cursor.execute(f"ALTER TABLE cicd_flow_templates DROP COLUMN {col}")
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

        # 自动迁移：为 cicd_agents 表添加前端挂载目录字段
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'cicd_agents')
            if columns and 'frontend_mount_dir' not in columns:
                cursor.execute(_add_col_sql('cicd_agents', 'frontend_mount_dir', "VARCHAR(255) DEFAULT ''"))
                conn.commit()
            if columns and 'nfs_server' not in columns:
                cursor.execute(_add_col_sql('cicd_agents', 'nfs_server', "VARCHAR(100) DEFAULT ''"))
                conn.commit()
            if columns and 'nfs_share' not in columns:
                cursor.execute(_add_col_sql('cicd_agents', 'nfs_share', "VARCHAR(200) DEFAULT ''"))
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：ddl_sync_logs 表添加 targets 列（一条 DDL 一条日志，目标执行结果 JSON 数组）
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'ddl_sync_logs')
            if columns and 'targets' not in columns:
                cursor.execute(_add_col_sql('ddl_sync_logs', 'targets', "TEXT DEFAULT ''"))
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：cicd_flow_templates 加 configs 列（前后端双份配置 JSON），存量旧字段迁移到 configs
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            columns = _get_columns(cursor, 'cicd_flow_templates')
            if columns and 'configs' not in columns:
                cursor.execute(_add_col_sql('cicd_flow_templates', 'configs', "TEXT DEFAULT ''"))
                conn.commit()
            conn.close()
        except Exception:
            pass
        try:
            for tpl in CicdFlowTemplate.query.all():
                if (tpl.configs or '').strip():
                    continue
                cfg = {'backend': {}, 'frontend': {}}
                cur_type = tpl.project_type or 'backend'
                cfg[cur_type] = {
                    'language': tpl.language or '',
                    'git_url': tpl.git_url or '',
                    'git_credential_id': tpl.git_credential_id,
                    'build_docker_image': tpl.build_docker_image or '',
                    'build_command': tpl.build_command or '',
                    'artifact_dirs': tpl.artifact_dirs or '',
                    'artifact_dir': tpl.artifact_dir or '',
                    'dockerfile_template_id': tpl.dockerfile_template_id,
                }
                tpl.configs = json.dumps(cfg, ensure_ascii=False)
            db.session.commit()
        except Exception:
            db.session.rollback()

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
            if columns and 'nickname_pinyin' not in columns:
                cursor.execute("ALTER TABLE users ADD COLUMN nickname_pinyin VARCHAR(128) DEFAULT ''")
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 自动迁移：synced_users 表补充手机号/邮箱/拼音列（表不存在则跳过）
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
            if scols and 'nickname_pinyin' not in scols:
                cursor.execute("ALTER TABLE synced_users ADD COLUMN nickname_pinyin VARCHAR(128) DEFAULT ''")
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

        # 自动迁移：audit_logs 表添加 permission 列（操作权限码 op:xxx）
        try:
            conn = db.engine.raw_connection()
            cursor = conn.cursor()
            acols = _get_columns(cursor, 'audit_logs')
            if acols and 'permission' not in acols:
                cursor.execute(_add_col_sql('audit_logs', 'permission', "VARCHAR(128) DEFAULT ''"))
                conn.commit()
            conn.close()
        except Exception:
            pass

        # 存量角色收编：系统只内置「超级管理员」「管理员」两个角色；
        # 其他角色（含此前内置的普通用户/运维人员等）统一取消内置保护，由用户自行创建/管理
        try:
            for r in Role.query.filter(Role.name != '超级管理员', Role.name != '管理员').all():
                if r.is_builtin:
                    r.is_builtin = False
            db.session.commit()
        except Exception:
            db.session.rollback()

        # 初始化预置角色（内置角色以 BUILTIN_ROLES 定义为准：缺失则创建，
        # 已存在则对齐权限——权限码变更后重启即自愈，避免旧码残留导致菜单/接口失效）
        for role_def in BUILTIN_ROLES:
            want_perms = json.dumps(role_def['permissions'], ensure_ascii=False)
            role = Role.query.filter_by(name=role_def['name'], is_builtin=True).first()
            if role is None:
                db.session.add(Role(
                    name=role_def['name'],
                    description=role_def['description'],
                    permissions=want_perms,
                    is_builtin=role_def.get('is_builtin', False),
                ))
            else:
                role.description = role_def['description']
                role.permissions = want_perms
        db.session.commit()

        # 管理员角色权限自动补全：新增权限码发布后自动并入（保证“拥有全部权限”）
        admin_role = Role.query.filter_by(name='管理员', is_builtin=True).first()
        if admin_role:
            # 权限码单一来源：menus 表（page + op）
            from modules.system.models import Menu
            all_codes = []
            for m in Menu.query.all():
                if m.perm_code:
                    all_codes.append(m.perm_code)
                for op in m.op_list():
                    all_codes.append(op['code'])
            all_codes = list(dict.fromkeys(all_codes))
            current = admin_role.permissions_list()
            missing = [c for c in all_codes if c not in current]
            if missing:
                admin_role.permissions = json.dumps(current + missing, ensure_ascii=False)
                db.session.commit()

        # 旧权限码迁移：全量角色中的废弃码替换为新码（支持一对多展开，自定义角色一并修复，幂等）
        legacy_map = {
            'page:collation': ['page:database'],
            'op:collation_fix': ['op:database_fix'],
            'op:deploy': ['op:deploy_project', 'op:deploy_env', 'op:deploy_service'],
        }
        for role in Role.query.all():
            migrated, changed = [], False
            for code in role.permissions_list():
                new_codes = legacy_map.get(code)
                if new_codes is None:
                    new_codes = [code]
                else:
                    changed = True
                for nc in new_codes:
                    if nc not in migrated:
                        migrated.append(nc)
            if changed:
                role.permissions = json.dumps(migrated, ensure_ascii=False)
        if db.session.dirty:
            db.session.commit()

        # 超级管理员独立表（super_admins）：本地逃生账号，不存 users（users 只放认证中心用户）
        # - 首次初始化：存量「超级管理员」角色用户迁移进 super_admins；无存量则按环境变量/默认 admin 创建
        # - 迁移后清理 users 中超管记录（认证中心同步用户无本地密码；超管走登录页「管理员登录」标签）
        super_role = Role.query.filter_by(name='超级管理员').first()
        from modules.system.models import SuperAdmin
        if db.session.query(SuperAdmin.id).first() is None:
            import os as _os
            super_name = (_os.getenv('SUPER_ADMIN_USERNAME') or 'admin').strip().lower()
            super_pass = _os.getenv('SUPER_ADMIN_PASSWORD') or 'admin123'
            migrated = []
            if super_role is not None:
                legacy_users = User.query.filter_by(role_id=super_role.id).all()
                for lu in legacy_users:
                    migrated.append(lu.username.strip().lower())
                    db.session.add(SuperAdmin(
                        username=lu.username.strip().lower(),
                        password_hash=lu.password_hash or generate_password_hash(super_pass),
                        nickname=lu.nickname or '',
                        is_active=lu.is_active,
                    ))
                    # 清理旧会话（记录将删除，防旧全权限会话残留）
                    from modules.system.session_cache import delete_user_sessions
                    delete_user_sessions(lu.id)
                    db.session.delete(lu)
            if not migrated:
                db.session.add(SuperAdmin(
                    username=super_name,
                    password_hash=generate_password_hash(super_pass),
                ))
            db.session.commit()
            if migrated:
                print(f'[bootstrap] 超级管理员已迁移到独立表: {", ".join(migrated)}（密码沿用本地哈希；无密码者使用默认 admin123，请登录后尽快修改）')
            elif super_pass == 'admin123' and not _os.getenv('SUPER_ADMIN_PASSWORD'):
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
            {'key': 'k8s_kubeconfig', 'value': '', 'description': 'K8s admin.conf 内容（服务信息页查看Pod日志用，粘贴完整文件内容）'},
            {'key': 'k8s_api_server', 'value': '', 'description': 'K8s API Server地址（可选，覆盖admin.conf中的server，如 https://192.168.x.x:6443）'},
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
