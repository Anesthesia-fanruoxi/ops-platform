"""MySQL 排序规则校验修复服务

数据源自动发现：从 environments 表 deploy_config 中提取含 mysql 中间件的环境，
连接端口优先取 product/{项目}-{环境}/middleware/mysql.yaml 中真实部署的 nodePort，
取不到再回退为 deploy_config 的 middleware_port + mysql 在中间件列表中的下标。

自定义数据源：用户手动录入的 MySQL 连接信息，存储在 collation_datasources 表。
实例 ID 规则：自动发现为纯数字（env.id），自定义为 'custom-{id}' 字符串。
"""
import json
import os
import re

import pymysql
import pymysql.cursors
from flask import current_app

from modules.deploy.models import Environment
from modules.database.models import CustomDatasource

# ── 目标排序规则常量 ──
TARGET_COLLATION = 'utf8mb4_0900_ai_ci'
TARGET_CHARSET = 'utf8mb4'
MAX_ROWS_THRESHOLD = 100000

# 系统库过滤
SYSTEM_DATABASES = ('information_schema', 'performance_schema', 'mysql', 'sys')


def _get_setting(key, default=''):
    """读取系统设置"""
    from modules.system.settings_service import get_setting
    return get_setting(key, default)


def _parse_ignore_projects(raw):
    """解析逗号分隔的忽略项目字符串为集合"""
    return {p.strip() for p in raw.split(',') if p.strip()}


def _middleware_names(middleware_list):
    """兼容两种存储格式：[{'name': 'mysql'}, ...] 和 ['mysql', ...]"""
    names = []
    for item in middleware_list:
        if isinstance(item, dict):
            names.append(item.get('name', ''))
        else:
            names.append(item)
    return names


def _get_mysql_nodeport(project_name, env_name):
    """从产物目录（yaml_output_dir 配置）的 mysql.yaml 中读取真实部署的 nodePort"""
    output_dir = _get_setting('yaml_output_dir', '')
    # 相对路径基于应用根目录解析
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(current_app.root_path, output_dir)
    yaml_path = os.path.join(
        output_dir, f'{project_name}-{env_name}', 'middleware', 'mysql.yaml'
    )
    try:
        with open(yaml_path, encoding='utf-8') as f:
            match = re.search(r'nodePort:\s*(\d+)', f.read())
            if match:
                return int(match.group(1))
    except OSError:
        pass
    return None


def discover_mysql_instances():
    """自动发现所有含 mysql 中间件的环境，返回连接信息列表"""
    host = _get_setting('k8s_master_ip', '')
    user = _get_setting('mysql_default_user', '')
    password = _get_setting('mysql_default_pass', '')

    if not host:
        return []

    # 忽略的项目：读取通用「项目忽略管理」(ignored_projects)，这些项目下的实例不展示
    ignore_projects = _parse_ignore_projects(_get_setting('ignored_projects', ''))

    environments = Environment.query.filter_by(is_deleted=False).all()
    instances = []

    for env in environments:
        if not env.deploy_config:
            continue
        try:
            config = json.loads(env.deploy_config)
        except (json.JSONDecodeError, TypeError):
            continue

        names = _middleware_names(config.get('middleware', []))
        if 'mysql' not in names:
            continue

        project_name = env.project.name if env.project else ''

        # 跳过被忽略的项目
        if project_name in ignore_projects:
            continue

        # 端口：优先取 product yaml 中真实 nodePort，回退为 base+index
        port = _get_mysql_nodeport(project_name, env.name)
        if port is None:
            base_port = config.get('middleware_port', 30090)
            port = base_port + names.index('mysql')

        instances.append({
            'id': env.id,
            'name': f'{project_name}-{env.name}' if project_name else env.name,
            'project': project_name,
            'env': env.name,
            'host': host,
            'port': port,
            'user': user,
            'password': password,
        })

    return instances


def discover_custom_instances():
    """获取所有自定义数据源，返回与 discover_mysql_instances 相同结构的列表"""
    sources = CustomDatasource.query.order_by(CustomDatasource.id).all()
    instances = []
    for s in sources:
        instances.append({
            'id': f'custom-{s.id}',
            'name': s.name,
            'project': s.project,
            'env': s.env,
            'host': s.host,
            'port': s.port,
            'user': s.user,
            'password': s.password,
            'source_type': 'custom',
            'description': s.description,
        })
    return instances


def get_instance_by_id(instance_id):
    """根据 instance_id 获取单个实例连接信息

    支持两种 ID 格式：
    - 纯数字 / 数字字符串：自动发现的实例（env.id）
    - 'custom-{id}'：自定义数据源
    """
    instance_id = str(instance_id)

    if instance_id.startswith('custom-'):
        # 自定义数据源
        custom_id = int(instance_id.split('-', 1)[1])
        s = CustomDatasource.query.get(custom_id)
        if not s:
            return None
        return {
            'id': f'custom-{s.id}',
            'name': s.name,
            'project': s.project,
            'env': s.env,
            'host': s.host,
            'port': s.port,
            'user': s.user,
            'password': s.password,
            'source_type': 'custom',
        }

    # 自动发现实例（兼容 int 和 str）
    try:
        env_id = int(instance_id)
    except (ValueError, TypeError):
        return None
    instances = discover_mysql_instances()
    for inst in instances:
        if inst['id'] == env_id:
            return inst
    return None


def get_connection(instance_id, database=None):
    """根据 instance_id 建立 PyMySQL 连接"""
    inst = get_instance_by_id(instance_id)
    if not inst:
        raise ValueError(f'未找到实例 ID={instance_id}')

    return pymysql.connect(
        host=inst['host'],
        port=inst['port'],
        user=inst['user'],
        password=inst['password'],
        database=database,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=10,
    )


# ── 核心校验逻辑（移植自 mysql-collation-check） ──

def column_needs_fix(column):
    """判断字段是否需要修复排序规则"""
    collation = column['COLLATION_NAME']
    charset = column['CHARACTER_SET_NAME']
    return collation is not None and (
        collation != TARGET_COLLATION or charset != TARGET_CHARSET
    )


def annotate_table(table, column_issues):
    """为表记录标注排序状态"""
    collation = table['TABLE_COLLATION'] or ''
    charset = collation.split('_')[0] if collation else ''
    issues = column_issues.get(table['TABLE_NAME'], [])

    table['TABLE_CHARSET'] = charset
    table['charset_mismatch'] = charset != TARGET_CHARSET
    table['table_need_fix'] = (
        table['charset_mismatch'] or collation != TARGET_COLLATION
    )
    table['COLUMN_ISSUES'] = issues
    table['COLUMN_ISSUE_COUNT'] = len(issues)
    table['need_fix'] = table['table_need_fix'] or bool(issues)
    return table


def fetch_column_issues(cursor, database):
    """查询指定库中排序规则异常的字段，返回 {TABLE_NAME: [{name,type,charset,collation}]}"""
    cursor.execute("""
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE,
               CHARACTER_SET_NAME, COLLATION_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND COLLATION_NAME IS NOT NULL
          AND (COLLATION_NAME != %s OR CHARACTER_SET_NAME != %s)
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """, (database, TARGET_COLLATION, TARGET_CHARSET))

    issues = {}
    for row in cursor.fetchall():
        issues.setdefault(row['TABLE_NAME'], []).append({
            'name': row['COLUMN_NAME'],
            'type': row['COLUMN_TYPE'],
            'charset': row['CHARACTER_SET_NAME'] or '-',
            'collation': row['COLLATION_NAME'] or '-'
        })
    return issues


def build_column_definition(column):
    """拼接 MODIFY COLUMN 的字段定义 SQL 片段"""
    parts = [column['COLUMN_TYPE']]
    if column['CHARACTER_SET_NAME'] is not None:
        parts.append(f'CHARACTER SET {TARGET_CHARSET} COLLATE {TARGET_COLLATION}')

    parts.append('NULL' if column['IS_NULLABLE'] == 'YES' else 'NOT NULL')

    default = column.get('COLUMN_DEFAULT')
    if default is not None:
        if default == 'CURRENT_TIMESTAMP':
            parts.append('DEFAULT CURRENT_TIMESTAMP')
        elif (column['COLUMN_TYPE'] in ('timestamp', 'datetime')
              and 'on update' in (column.get('EXTRA') or '').lower()):
            parts.append(f'DEFAULT {default}')
        else:
            parts.append(f"DEFAULT '{default}'")
    elif column['IS_NULLABLE'] == 'YES':
        # 可空字段显式补 DEFAULT NULL，避免 MODIFY 后丢失原默认值语义
        parts.append('DEFAULT NULL')

    extra = column.get('EXTRA') or ''
    if extra:
        parts.append(extra)

    comment = column.get('COLUMN_COMMENT') or ''
    if comment:
        parts.append(f"COMMENT '{comment}'")

    return ' '.join(parts)
