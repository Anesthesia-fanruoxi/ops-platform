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
from core.security import require_permission
from modules.collation.models import CustomDatasource
from modules.collation.service import (
    TARGET_COLLATION, TARGET_CHARSET, MAX_ROWS_THRESHOLD, SYSTEM_DATABASES,
    discover_mysql_instances, discover_custom_instances,
    get_connection, get_instance_by_id,
    column_needs_fix, annotate_table, fetch_column_issues,
)
from modules.collation.tasks import (
    register_task, get_task, COLLATION_LOG_FILE,
    _run_fix_database_task, _run_fix_table_task,
    _run_fix_all_tables_task, _run_fix_columns_task,
)
from modules.deploy.services.deploy_utils import _clear_log


# ── 实例发现（分组返回） ──

@require_permission('page:collation')
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
    """测试自定义数据源连接（新增/编辑前验证可达性）"""
    data = request.json
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

@require_permission('page:collation')
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

@require_permission('page:collation')
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

@require_permission('page:collation')
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

@require_permission('page:collation')
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

def _start_task(action, run_func, args):
    """通用异步任务启动：同实例并发锁 → 生成 task_key、清空单一日志文件、注册、起后台线程。
    返回 task_key；同实例已有任务进行中返回 None（调用方返回 409）。
    Redis 不可用时不做并发限制，直接运行。"""
    task_key = f'collation-{action}-{int(time.time() * 1000)}'
    lock_name = None
    from core.redis_client import is_available, set_if_absent
    instance_id = args[0] if args else None
    if is_available() and instance_id is not None:
        lock_name = f'lock:collation:{instance_id}'
        if not set_if_absent(lock_name, value='1', ttl=600000):
            return None
    _clear_log(COLLATION_LOG_FILE)
    register_task(task_key, lock_name=lock_name)
    app = current_app._get_current_object()
    t = threading.Thread(target=run_func, args=(app, task_key, *args), daemon=True)
    t.start()
    return task_key


@require_permission('op:collation_fix')
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


@require_permission('op:collation_fix')
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


@require_permission('op:collation_fix')
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


@require_permission('op:collation_fix')
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


def collation_stream():
    """排序修正进度流 - 读取单一日志文件实时推送（已登录即可，操作权限由触发接口校验）"""
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

@require_permission('page:collation')
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
