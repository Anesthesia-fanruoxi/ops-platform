# -*- coding: utf-8 -*-
"""
MySQL 排序规则校验修复接口
"""
import os
import json
import time
import threading
from datetime import datetime

from flask import request, make_response, Response, current_app

from core.db import db
from core.response import success_response, error_response
from core.security import require_permission, require_any_permission
from modules.database.models import CustomDatasource, DdlSyncTask, DdlSyncLog
from modules.database.ddl_sync import ddl_sync_manager
from modules.database.service import (
    TARGET_COLLATION, TARGET_CHARSET, MAX_ROWS_THRESHOLD, SYSTEM_DATABASES,
    discover_mysql_instances, discover_custom_instances,
    get_connection, get_instance_by_id,
    column_needs_fix, annotate_table, fetch_column_issues,
)
from modules.database.tasks import (
    register_task, get_task, COLLATION_LOG_FILE,
    _run_fix_database_task, _run_fix_table_task,
    _run_fix_all_tables_task, _run_fix_columns_task,
    _run_sync_structure_task,
)
from modules.database.schema_diff import (
    fetch_schema_metadata, compare_schemas, build_sync_plan_sql,
)
from modules.deploy.services.deploy_utils import _clear_log


# ── 实例发现（分组返回） ──

@require_any_permission('page:database', 'page:schema')
def list_instances():
    """获取所有 MySQL 实例（分组：自动发现 + 自定义数据源）"""
    try:
        auto_instances = discover_mysql_instances()
        custom_instances = discover_custom_instances()
        # 不返回密码
        safe_auto = [
            {'id': i['id'], 'name': i['name'], 'project': i['project'],
             'env': i['env'], 'host': i['host'], 'port': i['port'],
             'source_type': 'auto'}
            for i in auto_instances
        ]
        safe_custom = [
            {'id': i['id'], 'name': i['name'], 'project': i['project'],
             'env': i['env'], 'host': i['host'], 'port': i['port'],
             'source_type': 'custom', 'description': i.get('description', '')}
            for i in custom_instances
        ]
        return success_response({'auto': safe_auto, 'custom': safe_custom})
    except Exception as e:
        return error_response(str(e))


# ── 自定义数据源 CRUD ──

@require_permission('page:datasources')
def list_datasources():
    """获取所有自定义数据源"""
    sources = CustomDatasource.query.order_by(CustomDatasource.id).all()
    return success_response([s.to_dict() for s in sources])


@require_permission('op:datasource')
def create_datasource():
    """新增自定义数据源"""
    data = request.json
    name = (data.get('name') or '').strip()
    host = (data.get('host') or '').strip()
    port = data.get('port', 3306)
    user = (data.get('user') or 'root').strip()
    password = data.get('password', '')
    project = (data.get('project') or '').strip()
    env = (data.get('env') or '').strip()
    description = (data.get('description') or '').strip()

    if not name:
        return error_response('数据源名称不能为空', 400)
    if not host:
        return error_response('主机地址不能为空', 400)
    if not port or not isinstance(port, int):
        return error_response('端口必须为整数', 400)

    source = CustomDatasource(
        name=name, host=host, port=port, user=user,
        password=password, project=project, env=env,
        description=description,
    )
    db.session.add(source)
    db.session.commit()
    return success_response(source.to_dict(), '数据源创建成功')


@require_permission('op:datasource')
def update_datasource(source_id):
    """更新自定义数据源"""
    source = CustomDatasource.query.get(source_id)
    if not source:
        return error_response('数据源不存在', 404)

    data = request.json
    if 'name' in data:
        source.name = (data['name'] or '').strip() or source.name
    if 'host' in data:
        source.host = (data['host'] or '').strip() or source.host
    if 'port' in data:
        source.port = data['port'] if isinstance(data['port'], int) else source.port
    if 'user' in data:
        source.user = (data['user'] or '').strip() or source.user
    if 'password' in data:
        source.password = data['password']
    if 'project' in data:
        source.project = (data['project'] or '').strip()
    if 'env' in data:
        source.env = (data['env'] or '').strip()
    if 'description' in data:
        source.description = (data['description'] or '').strip()

    db.session.commit()
    return success_response(source.to_dict(), '数据源更新成功')


@require_permission('op:datasource')
def delete_datasource(source_id):
    """删除自定义数据源"""
    source = CustomDatasource.query.get(source_id)
    if not source:
        return error_response('数据源不存在', 404)
    db.session.delete(source)
    db.session.commit()
    return success_response(None, '数据源已删除')


@require_permission('page:datasources')
def test_datasource_connection():
    """测试数据源连接。

    - 传 datasource_id：已保存数据源，后端直接查库取完整配置（host/port/user/密码），
      前端无需也不应传密码（列表行「测试」按钮场景）
    - 不传 id：表单校验（新建/编辑前），用前端传入的 host/port/user/password
    """
    data = request.json
    ds_id = data.get('datasource_id')
    if ds_id:
        from modules.database.models import CustomDatasource
        source = CustomDatasource.query.get(ds_id)
        if not source:
            return error_response('数据源不存在', 404)
        host = (source.host or '').strip()
        port = source.port or 3306
        user = (source.user or 'root').strip()
        password = source.password or ''
    else:
        host = (data.get('host') or '').strip()
        port = data.get('port', 3306)
        user = (data.get('user') or 'root').strip()
        password = data.get('password', '')

    if not host:
        return error_response('主机地址不能为空', 400)

    import pymysql
    import pymysql.cursors
    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=password,
            charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
        )
        conn.close()
        return success_response(None, '连接成功')
    except Exception as e:
        return error_response(f'连接失败: {e}')


# ── 数据库列表 ──

@require_any_permission('page:database', 'page:schema')
def list_databases():
    """获取指定实例的数据库列表"""
    instance_id = request.args.get('instance_id', '')
    if not instance_id:
        return error_response('缺少 instance_id 参数', 400)

    try:
        conn = get_connection(instance_id)
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT SCHEMA_NAME, DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
                FROM information_schema.SCHEMATA
                WHERE SCHEMA_NAME NOT IN (%s, %s, %s, %s)
            """, SYSTEM_DATABASES)
            databases = cursor.fetchall()
        conn.close()
        return success_response(databases)
    except Exception as e:
        return error_response(f'连接失败: {e}')


# ── 表列表 ──

@require_any_permission('page:database', 'page:schema')
def list_tables(database):
    """获取指定库的表列表（含排序状态标注）"""
    instance_id = request.args.get('instance_id', '')
    if not instance_id:
        return error_response('缺少 instance_id 参数', 400)

    try:
        conn = get_connection(instance_id, database)
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT TABLE_NAME, TABLE_COLLATION, TABLE_ROWS, DATA_LENGTH, TABLE_COMMENT
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
            """, (database,))
            tables = cursor.fetchall()
            issues = fetch_column_issues(cursor, database)
            for table in tables:
                annotate_table(table, issues)
        conn.close()
        return success_response(tables)
    except Exception as e:
        return error_response(f'查询失败: {e}')


# ── 字段详情 ──

@require_any_permission('page:database', 'page:schema')
def list_columns(database, table):
    """获取指定表的字段详情"""
    instance_id = request.args.get('instance_id', '')
    if not instance_id:
        return error_response('缺少 instance_id 参数', 400)

    try:
        conn = get_connection(instance_id, database)
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COLUMN_NAME, COLUMN_TYPE, CHARACTER_SET_NAME, COLLATION_NAME,
                       IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
            """, (database, table))
            columns = cursor.fetchall()
            for col in columns:
                col['need_fix'] = column_needs_fix(col)
        conn.close()
        return success_response(columns)
    except Exception as e:
        return error_response(f'查询失败: {e}')


# ── 字段问题汇总 ──

@require_permission('page:database')
def list_column_issues(database):
    """获取指定库的字段问题汇总"""
    instance_id = request.args.get('instance_id', '')
    if not instance_id:
        return error_response('缺少 instance_id 参数', 400)

    try:
        conn = get_connection(instance_id, database)
        with conn.cursor() as cursor:
            issues = fetch_column_issues(cursor, database)
            # 各表预估行数（取自元数据 TABLE_ROWS，非实时统计）
            row_counts = {}
            if issues:
                cursor.execute("""
                    SELECT TABLE_NAME, TABLE_ROWS
                    FROM information_schema.TABLES
                    WHERE TABLE_SCHEMA = %s
                """, (database,))
                for r in cursor.fetchall():
                    row_counts[r['TABLE_NAME']] = r['TABLE_ROWS'] or 0
            result = [
                {'table': t, 'columns': cols, 'row_count': row_counts.get(t, 0)}
                for t, cols in issues.items()
            ]
        conn.close()
        return success_response(result, msg=f'共 {len(result)} 张表存在字段问题')
    except Exception as e:
        return error_response(f'查询失败: {e}')


# ── 异步修复（SSE 实时日志推送） ──

def _start_task(action, run_func, args, lock_instances=None):
    """通用异步任务启动：实例并发锁 → 生成 task_key、清空单一日志文件、注册、起后台线程。
    lock_instances 为需加锁的实例 id 列表（一源多目标同步时锁全部目标实例）；
    未显式指定时默认锁 args[0]。
    任一实例已有任务进行中则整体拒绝返回 None（调用方返回 409）。
    Redis 不可用时不做并发限制，直接运行。"""
    task_key = f'database-{action}-{int(time.time() * 1000)}'
    lock_names = []
    from core.redis_client import is_available, set_if_absent, cache_delete
    if lock_instances is None:
        instance_id = args[0] if args else None
        lock_instances = [instance_id] if instance_id is not None else []
    if is_available() and lock_instances:
        for iid in lock_instances:
            name = f'lock:database:{iid}'
            if not set_if_absent(name, value='1', ttl=600000):
                # 已占的锁回滚释放，避免部分占用
                for got in lock_names:
                    cache_delete(got)
                return None
            lock_names.append(name)
    _clear_log(COLLATION_LOG_FILE)
    register_task(task_key, lock_names=lock_names or None)
    app = current_app._get_current_object()
    t = threading.Thread(target=run_func, args=(app, task_key, *args), daemon=True)
    t.start()
    return task_key


@require_permission('op:database_fix')
def fix_database_async():
    """异步修复数据库级排序（SSE 日志推送）"""
    data = request.json
    instance_id = data.get('instance_id')
    database = data.get('database')
    if not instance_id or not database:
        return error_response('缺少参数', 400)
    task_key = _start_task('fixdb', _run_fix_database_task, (instance_id, database))
    if not task_key:
        return error_response('该实例已有修复任务进行中，请稍后再试', 409)
    return success_response({'task_key': task_key, 'status': 'running'}, '修复任务已提交')


@require_permission('op:database_fix')
def fix_table_async():
    """异步修复单表排序（SSE 日志推送）"""
    data = request.json
    instance_id = data.get('instance_id')
    database = data.get('database')
    table = data.get('table')
    if not instance_id or not database or not table:
        return error_response('缺少参数', 400)
    task_key = _start_task('fixtbl', _run_fix_table_task, (instance_id, database, table))
    if not task_key:
        return error_response('该实例已有修复任务进行中，请稍后再试', 409)
    return success_response({'task_key': task_key, 'status': 'running'}, '修复任务已提交')


@require_permission('op:database_fix')
def fix_all_tables_async():
    """异步一键修复所有表（SSE 日志推送，超阈值跳过）"""
    data = request.json
    instance_id = data.get('instance_id')
    database = data.get('database')
    threshold = data.get('threshold', MAX_ROWS_THRESHOLD)
    if not instance_id or not database:
        return error_response('缺少参数', 400)
    task_key = _start_task('fixall', _run_fix_all_tables_task, (instance_id, database, threshold))
    if not task_key:
        return error_response('该实例已有修复任务进行中，请稍后再试', 409)
    return success_response({'task_key': task_key, 'status': 'running'}, '修复任务已提交')


@require_permission('op:database_fix')
def fix_columns_async():
    """异步修复指定字段（SSE 日志推送，单表模式无视阈值）"""
    data = request.json
    instance_id = data.get('instance_id')
    database = data.get('database')
    threshold = data.get('threshold', MAX_ROWS_THRESHOLD)
    selected = data.get('columns')
    single_table = data.get('table')
    if not instance_id or not database or not selected:
        return error_response('缺少参数', 400)
    task_key = _start_task('fixcol', _run_fix_columns_task, (instance_id, database, selected, threshold, single_table))
    if not task_key:
        return error_response('该实例已有修复任务进行中，请稍后再试', 409)
    return success_response({'task_key': task_key, 'status': 'running'}, '修复任务已提交')


# ── 表结构对比与同步 ──

# 分类映射：创建=目标缺失，修改=结构差异，删除=目标多余
_GROUP_BY_STATUS = {'missing': 'create', 'diff': 'modify', 'extra': 'drop'}


def _object_brief(row):
    """生成对象摘要描述（前端直接展示）"""
    ops = row.get('ops') or {}
    if row['status'] == 'missing':
        return (ops.get('create') or [{}])[0].get('desc', '')
    if row['status'] == 'extra':
        return '源库不存在该对象'
    # diff：表按字段/索引变更数汇总，视图/事件直接展示变更内容
    if row.get('object_type') == '表':
        c = len(ops.get('create') or [])
        m = len(ops.get('modify') or [])
        d = len(ops.get('drop') or [])
        desc = f'新建 {c} · 修改 {m}'
        if d:
            desc += f' · 多余 {d}（不处理）'
        return desc
    mods = ops.get('modify') or ops.get('create') or []
    return mods[0].get('desc', '') if mods else ''


def _to_compare_view(result):
    """对比结果转前端展示视图：每对象附加 group/desc，剔除完全一致的对象"""
    tables = []
    for row in result['tables']:
        group = _GROUP_BY_STATUS.get(row['status'])
        if not group:
            continue
        row = dict(row)
        row['group'] = group
        row['desc'] = _object_brief(row)
        tables.append(row)
    result['tables'] = tables
    return result


def _compare_structure_payload(data):
    """解析对比参数并执行对比，返回 (result, error_response)；失败时 result 为 None"""
    source_instance_id = data.get('source_instance_id')
    target_instance_id = data.get('target_instance_id')
    source_database = data.get('source_database')
    target_database = data.get('target_database') or source_database
    project = (data.get('project') or '').strip()
    if not source_instance_id or not target_instance_id or not source_database:
        return None, error_response('缺少参数（源/目标实例、源数据库）', 400)

    src_conn = tgt_conn = None
    try:
        src_conn = get_connection(source_instance_id)
        tgt_conn = (src_conn if target_instance_id == source_instance_id
                    else get_connection(target_instance_id))
        src_meta = fetch_schema_metadata(src_conn, source_database)
        tgt_meta = fetch_schema_metadata(tgt_conn, target_database)
        result = compare_schemas(src_meta, tgt_meta)
        _to_compare_view(result)
        result['project'] = project
        result['source'] = {
            'instance_id': str(source_instance_id),
            'name': (get_instance_by_id(source_instance_id) or {}).get('name', str(source_instance_id)),
            'database': source_database,
        }
        result['target'] = {
            'instance_id': str(target_instance_id),
            'name': (get_instance_by_id(target_instance_id) or {}).get('name', str(target_instance_id)),
            'database': target_database,
        }
        return result, None
    except ValueError as e:
        return None, error_response(str(e), 404)
    except Exception as e:
        return None, error_response(f'对比失败: {e}')
    finally:
        if src_conn:
            src_conn.close()
        if tgt_conn is not None and tgt_conn is not src_conn:
            tgt_conn.close()


@require_permission('page:schema')
def compare_structure():
    """表结构对比：源库 → 目标库（表/字段/索引/表选项差异）"""
    result, err = _compare_structure_payload(request.json or {})
    if err:
        return err
    return success_response(result)


@require_permission('page:schema')
def sync_structure_sql():
    """预览同步 SQL（不执行，仅生成文本）"""
    result, err = _compare_structure_payload(request.json or {})
    if err:
        return err
    sql_text = build_sync_plan_sql(result)
    need_sync = [t['table'] for t in result['tables'] if t['status'] in ('missing', 'diff')]
    return success_response({'sql': sql_text, 'tables': need_sync})


@require_permission('op:structure_sync')
def sync_structure_async():
    """异步执行表结构同步（SSE 日志推送，一源多目标，全部目标实例加并发锁）

    支持两种入参：
    - targets: [{'instance_id':..., 'database':..., 'tables': [...]|缺省}]（多目标）
    - target_instance_id / target_database / tables（单目标，向下兼容）
    """
    data = request.json or {}
    source_instance_id = data.get('source_instance_id')
    source_database = data.get('source_database')
    if not source_instance_id or not source_database:
        return error_response('缺少参数（源实例、源数据库）', 400)

    targets = []
    for t in data.get('targets') or []:
        tid = t.get('instance_id')
        if not tid:
            continue
        targets.append({
            'instance_id': tid,
            'database': t.get('database') or source_database,
            'tables': t.get('tables') or None,
        })
    if not targets:
        # 单目标旧参数兼容
        target_instance_id = data.get('target_instance_id')
        if not target_instance_id:
            return error_response('缺少参数（目标实例）', 400)
        targets.append({
            'instance_id': target_instance_id,
            'database': data.get('target_database') or source_database,
            'tables': data.get('tables') or None,
        })

    lock_instances = [t['instance_id'] for t in targets]
    task_key = _start_task('sync', _run_sync_structure_task,
                           (source_instance_id, source_database, targets),
                           lock_instances=lock_instances)
    if not task_key:
        return error_response('目标实例已有任务进行中，请稍后再试', 409)
    return success_response({'task_key': task_key, 'status': 'running'}, '同步任务已提交')


def database_stream():
    """任务进度流 - 读取单一日志文件实时推送（已登录即可，操作权限由触发接口校验）"""
    task_key = request.args.get('task_key', '')
    if not task_key:
        return error_response('缺少 task_key 参数', 400)
    log_file = COLLATION_LOG_FILE

    def generate():
        # 等待日志文件创建
        if not os.path.exists(log_file):
            for _ in range(30):
                if os.path.exists(log_file):
                    break
                time.sleep(0.5)
            else:
                yield f"data: {json.dumps({'done': True, 'success': False, 'message': '日志文件未创建'})}\n\n"
                return

        with open(log_file, 'r', encoding='utf-8') as f:
            # 统一用 readline 逐行读取（从头开始，任务启动时文件已清空）；
            # 每推送一行短暂停顿，使日志像终端一样丝滑地逐行呈现，避免多条瞬间堆叠
            while True:
                line = f.readline()
                if line:
                    line = line.strip()
                    if line:
                        parsed = _parse_collation_log(line)
                        if parsed:
                            yield f"data: {json.dumps(parsed, ensure_ascii=False)}\n\n"
                        if '[DONE]' in line or '[FAILED]' in line:
                            yield f"data: {json.dumps({'done': True, 'success': '[DONE]' in line}, ensure_ascii=False)}\n\n"
                            return
                        time.sleep(0.03)
                    continue
                # 暂无新内容：任务已到终态则结束流，否则短轮询等待
                t = get_task(task_key)
                if t and t.get('status') in ('completed', 'failed'):
                    yield f"data: {json.dumps({'done': True, 'success': t['status'] == 'completed'}, ensure_ascii=False)}\n\n"
                    return
                time.sleep(0.2)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def _parse_collation_log(line):
    """解析日志行 [时间] [级别] [执行逻辑] [数据源] [数据库] 修复结果 为 SSE 数据"""
    try:
        if not line.startswith('['):
            return {'message': line}
        fields = []
        rest = line
        # 提取前 5 个 [xxx] 字段：时间 / 级别 / 执行逻辑 / 数据源 / 数据库
        for _ in range(5):
            if not rest.startswith('['):
                break
            end = rest.index(']', 1)
            fields.append(rest[1:end])
            rest = rest[end + 1:].lstrip()
        if len(fields) >= 5:
            return {'time': fields[0], 'level': fields[1], 'op': fields[2],
                    'source': fields[3], 'database': fields[4], 'message': rest.strip()}
        if len(fields) >= 2:
            return {'time': fields[0], 'level': fields[1], 'message': rest.strip()}
        return {'message': line}
    except Exception:
        return {'message': line}


# ── 导出报告 ──

@require_permission('page:database')
def download_report(database):
    """生成并下载 HTML 校验报告"""
    instance_id = request.args.get('instance_id', '')
    if not instance_id:
        return error_response('缺少 instance_id 参数', 400)

    try:
        html = _build_report(instance_id, database)
        response = make_response(html)
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Content-Disposition'] = (
            f'attachment; filename=report_{database}_{datetime.now():%Y%m%d%H%M%S}.html'
        )
        return response
    except Exception as e:
        return error_response(f'生成报告失败: {e}')


def _build_report(instance_id, database):
    """查数据 + 拼 HTML 报告"""
    conn = get_connection(instance_id, database)
    cursor = conn.cursor()

    # 数据库级别
    cursor.execute("""
        SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
        FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s
    """, (database,))
    db_info = cursor.fetchone()

    # 表级别
    cursor.execute("""
        SELECT TABLE_NAME, TABLE_COLLATION, TABLE_ROWS
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """, (database,))
    tables = cursor.fetchall()

    table_ok = []
    table_fix = []
    for t in tables:
        collation = t['TABLE_COLLATION'] or ''
        charset = collation.split('_')[0] if collation else ''
        t['TABLE_CHARSET'] = charset
        t['need_fix'] = charset != TARGET_CHARSET or collation != TARGET_COLLATION
        (table_fix if t['need_fix'] else table_ok).append(t)

    # 字段级别
    issues = fetch_column_issues(cursor, database)
    col_fix_count = sum(len(cols) for cols in issues.values())

    conn.close()

    # 拼 HTML
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    db_charset = db_info['DEFAULT_CHARACTER_SET_NAME'] if db_info else '-'
    db_collation = db_info['DEFAULT_COLLATION_NAME'] if db_info else '-'
    db_ok = (db_charset == TARGET_CHARSET and db_collation == TARGET_COLLATION)

    def row_html(t):
        status_cls = 'ok' if not t['need_fix'] else 'fix'
        status_txt = '已符合' if not t['need_fix'] else '需修复'
        return (
            f'<tr><td>{t["TABLE_NAME"]}</td>'
            f'<td>{t.get("TABLE_CHARSET", "-")}</td>'
            f'<td>{t["TABLE_COLLATION"]}</td>'
            f'<td>{(t["TABLE_ROWS"] or 0):,}</td>'
            f'<td class="{status_cls}">{status_txt}</td></tr>'
        )

    def col_groups_html(issues_dict):
        if not issues_dict:
            return '<p style="color:#52c41a">所有字段已符合要求</p>'
        parts = []
        for table, cols in sorted(issues_dict.items()):
            rows = ''.join(
                f'<tr><td>{c["name"]}</td><td>{c["type"]}</td>'
                f'<td>{c["charset"]}</td><td>{c["collation"]}</td></tr>'
                for c in cols
            )
            parts.append(f'''
            <div class="col-group">
                <div class="col-group-title">
                    <span class="table-name">{table}</span>
                    <span class="badge">{len(cols)} 个字段</span>
                </div>
                <table>
                    <tr><th>字段</th><th>类型</th><th>字符集</th><th>排序规则</th></tr>
                    {rows}
                </table>
            </div>''')
        return '\n'.join(parts)

    table_fix_html = (
        f'<table><tr><th>表名</th><th>字符集</th><th>排序规则</th><th>行数</th><th>状态</th></tr>'
        f'{"".join(row_html(t) for t in table_fix)}</table>'
        if table_fix else '<p style="color:#52c41a">所有表已符合要求</p>'
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>MySQL 排序规则校验报告 - {database}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f0f2f5; color: #333; margin: 0; padding: 24px; }}
.container {{ max-width: 1100px; margin: 0 auto; }}
.header {{ background: linear-gradient(135deg, #1890ff, #096dd9); color: white; padding: 28px 36px; border-radius: 12px 12px 0 0; }}
.header h1 {{ margin: 0 0 6px; font-size: 24px; font-weight: 600; }}
.header p {{ margin: 0; opacity: .85; font-size: 14px; }}
.card {{ background: white; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.06); padding: 28px 32px; margin-bottom: 20px; }}
.stats {{ display: flex; gap: 16px; margin-bottom: 24px; }}
.stat {{ flex: 1; background: white; border-radius: 10px; padding: 18px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
.stat .num {{ font-size: 32px; font-weight: 700; }}
.stat .label {{ font-size: 13px; color: #999; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
th {{ padding: 10px 14px; text-align: left; background: #fafafa; font-weight: 600; color: #666; font-size: 13px; border-bottom: 2px solid #f0f0f0; }}
td {{ padding: 9px 14px; text-align: left; border-bottom: 1px solid #f5f5f5; font-size: 13px; }}
.ok {{ color: #52c41a; font-weight: 600; }}
.fix {{ color: #fa541c; font-weight: 600; }}
h2 {{ font-size: 17px; margin: 24px 0 8px; padding-bottom: 6px; border-bottom: 2px solid #f0f0f0; }}
.col-group {{ margin-bottom: 16px; border: 1px solid #f0f0f0; border-radius: 8px; overflow: hidden; }}
.col-group-title {{ padding: 12px 16px; background: #fafafa; display: flex; align-items: center; gap: 10px; }}
.table-name {{ font-weight: 600; font-size: 14px; }}
.badge {{ background: #fff2e8; color: #fa541c; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 500; }}
.col-group table {{ margin-top: 0; }}
.col-group th {{ background: #fff; font-size: 12px; }}
.footer {{ text-align: center; color: #bbb; font-size: 12px; margin-top: 36px; }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>MySQL 排序规则校验报告</h1>
        <p>数据库：<strong>{database}</strong> | 目标排序规则：<strong>{TARGET_COLLATION}</strong> | 生成时间：{now}</p>
    </div>
    <div class="card">
        <div class="stats">
            <div class="stat"><div class="num" style="color:#1890ff">{len(tables)}</div><div class="label">总表数</div></div>
            <div class="stat"><div class="num" style="color:#52c41a">{len(table_ok)}</div><div class="label">已符合</div></div>
            <div class="stat"><div class="num" style="color:#ff4d4f">{len(table_fix)}</div><div class="label">需修复表</div></div>
            <div class="stat"><div class="num" style="color:#faad14">{col_fix_count}</div><div class="label">需修复字段</div></div>
        </div>
        <h2>数据库级别</h2>
        <table>
            <tr><th>字符集</th><th>排序规则</th><th>状态</th></tr>
            <tr><td>{db_charset}</td><td>{db_collation}</td>
                <td class="{"ok" if db_ok else "fix"}">{"已符合" if db_ok else "需修复"}</td></tr>
        </table>
        <h2>表级别 - 需修复 ({len(table_fix)})</h2>
        {table_fix_html}
        <h2>字段级别 - 需修复 ({col_fix_count})</h2>
        {col_groups_html(issues)}
    </div>
    <div class="footer">MySQL 排序规则校验工具 - 自动生成</div>
</div>
</body>
</html>"""
    return html


# ── DDL 自动同步 ──

def _all_sync_instances():
    """全部可参与 DDL 同步的实例（自动发现 + 自定义数据源，统一结构）"""
    insts = []
    for i in discover_mysql_instances():
        insts.append({'id': i['id'], 'name': i['name'], 'project': i['project'],
                      'env': i['env'], 'host': i['host'], 'port': i['port'],
                      'source_type': 'auto'})
    for i in discover_custom_instances():
        insts.append({'id': i['id'], 'name': i['name'], 'project': i['project'],
                      'env': i['env'], 'host': i['host'], 'port': i['port'],
                      'source_type': 'custom', 'description': i.get('description', '')})
    return insts


@require_permission('page:ddl_sync')
def ddl_sync_projects():
    """获取数据源中出现过的全部项目名（去重）"""
    try:
        projects = sorted({i['project'] for i in _all_sync_instances() if i['project']})
        return success_response(projects)
    except Exception as e:
        return error_response(str(e))


@require_permission('page:ddl_sync')
def ddl_sync_instances():
    """获取实例列表；不传 project 返回全量（前端名称映射用）"""
    project = request.args.get('project', '')
    try:
        insts = _all_sync_instances()
        if project:
            insts = [i for i in insts if i['project'] == project]
        return success_response(insts)
    except Exception as e:
        return error_response(str(e))


def _task_with_runtime(task):
    """任务字典 + 运行态（各源是否监听中、最近同步时间）"""
    data = task.to_dict()
    status_map = ddl_sync_manager.status_map()
    data['listening'] = {
        str(iid): bool(status_map.get((task.id, str(iid))))
        for iid in task.source_list()
    }
    last = DdlSyncLog.query.filter_by(task_id=task.id).order_by(DdlSyncLog.created_at.desc()).first()
    data['last_sync_at'] = last.created_at.strftime('%Y-%m-%d %H:%M:%S') if last and last.created_at else None
    return data


@require_permission('page:ddl_sync')
def ddl_sync_tasks_list():
    """任务列表（附运行状态）"""
    tasks = DdlSyncTask.query.order_by(DdlSyncTask.id.desc()).all()
    return success_response([_task_with_runtime(t) for t in tasks])


def _parse_task_payload(data):
    """解析创建/编辑任务参数，返回 (fields, error_response)；同步范围为全部库（系统库自动跳过）"""
    name = (data.get('name') or '').strip()
    project = (data.get('project') or '').strip()
    sources = [str(s) for s in (data.get('sources') or [])]
    ignored = [str(s) for s in (data.get('ignored') or [])]
    if not name:
        return None, error_response('任务名称不能为空', 400)
    if len(sources) < 2:
        return None, error_response('至少勾选 2 个数据源才能组成同步', 400)
    if len(set(sources)) != len(sources):
        return None, error_response('数据源不能重复勾选', 400)
    bad = [s for s in ignored if s not in sources]
    if bad:
        return None, error_response('忽略同步只能应用于已勾选的数据源', 400)
    return {'name': name, 'project': project, 'database': '',
            'sources': json.dumps(sources, ensure_ascii=False),
            'ignored': json.dumps(ignored, ensure_ascii=False)}, None


@require_permission('op:ddl_sync')
def ddl_sync_create_task():
    """创建同步任务（以当前 binlog 位点为基线，只同步创建后的新变更）"""
    fields, err = _parse_task_payload(request.json or {})
    if err:
        return err
    task = DdlSyncTask(**fields, enabled=True)
    db.session.add(task)
    db.session.commit()
    ddl_sync_manager.reload()
    return success_response(_task_with_runtime(task), '同步任务创建成功')


@require_permission('op:ddl_sync')
def ddl_sync_update_task(task_id):
    """编辑任务（随时变更勾选/忽略，配置即时生效）"""
    task = DdlSyncTask.query.get(task_id)
    if not task:
        return error_response('任务不存在', 404)
    fields, err = _parse_task_payload(request.json or {})
    if err:
        return err
    for k, v in fields.items():
        setattr(task, k, v)
    db.session.commit()
    ddl_sync_manager.reload()
    return success_response(_task_with_runtime(task), '任务更新成功')


@require_permission('op:ddl_sync')
def ddl_sync_toggle_task(task_id):
    """启用/暂停任务"""
    task = DdlSyncTask.query.get(task_id)
    if not task:
        return error_response('任务不存在', 404)
    task.enabled = not task.enabled
    db.session.commit()
    ddl_sync_manager.reload()
    return success_response(_task_with_runtime(task), '任务已启用' if task.enabled else '任务已暂停')


@require_permission('op:ddl_sync')
def ddl_sync_delete_task(task_id):
    """删除任务（停监听，同步日志保留）"""
    task = DdlSyncTask.query.get(task_id)
    if not task:
        return error_response('任务不存在', 404)
    db.session.delete(task)
    db.session.commit()
    ddl_sync_manager.reload()
    return success_response(None, '任务已删除')


@require_permission('page:ddl_sync')
def ddl_sync_logs():
    """同步日志（按任务过滤，时间倒序）"""
    task_id = request.args.get('task_id', type=int)
    limit = min(request.args.get('limit', 200, type=int) or 200, 1000)
    q = DdlSyncLog.query
    if task_id:
        q = q.filter_by(task_id=task_id)
    logs = q.order_by(DdlSyncLog.created_at.desc(), DdlSyncLog.id.desc()).limit(limit).all()
    # 附带实例名映射，前端直接展示
    names = {}
    for l in logs:
        for iid in (l.source_id, l.target_id):
            if iid and iid not in names:
                inst = get_instance_by_id(iid)
                names[iid] = inst['name'] if inst else iid
    data = [dict(l.to_dict(),
                 source_name=names.get(l.source_id, l.source_id),
                 target_name=names.get(l.target_id, '') if l.target_id else '')
            for l in logs]
    return success_response(data)


@require_permission('page:ddl_sync')
def ddl_sync_log_stream(task_id):
    """SSE 实时日志流：先回放最近 100 条历史（时间正序），之后轮询增量持续推送。
    客户端断开/任务不存在时自然结束；每 15s 发心跳注释防中间层断连。"""
    app = current_app._get_current_object()
    HISTORY_LIMIT = 100

    def _payload(l):
        inst = get_instance_by_id(l.source_id)
        return dict(l.to_dict(), source_name=inst['name'] if inst else l.source_id)

    def generate():
        last_id = 0
        try:
            # 历史回放：最近 N 条按时间正序推送
            with app.app_context():
                logs = DdlSyncLog.query.filter_by(task_id=task_id) \
                    .order_by(DdlSyncLog.id.desc()).limit(HISTORY_LIMIT).all()
                logs = list(reversed(logs))
                payloads = [_payload(l) for l in logs]
                last_id = logs[-1].id if logs else 0
            for p in payloads:
                yield f'data: {json.dumps(p, ensure_ascii=False)}\n\n'

            idle_sec = 0
            while True:
                time.sleep(1)
                # 增量轮询：id 大于已推送的最大 id
                with app.app_context():
                    new_logs = DdlSyncLog.query.filter(
                        DdlSyncLog.task_id == task_id, DdlSyncLog.id > last_id,
                    ).order_by(DdlSyncLog.id.asc()).limit(200).all()
                    payloads = [_payload(l) for l in new_logs]
                    if new_logs:
                        last_id = new_logs[-1].id
                if payloads:
                    idle_sec = 0
                    for p in payloads:
                        yield f'data: {json.dumps(p, ensure_ascii=False)}\n\n'
                else:
                    idle_sec += 1
                    if idle_sec % 15 == 0:
                        yield ': ping\n\n'  # 心跳保活
        except GeneratorExit:
            return
        except Exception:
            return

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
