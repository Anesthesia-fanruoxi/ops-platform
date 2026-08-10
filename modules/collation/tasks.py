# -*- coding: utf-8 -*-
"""
排序修正异步任务管理 + 后台执行函数

每个修复操作以后台线程执行，逐条 ALTER 写入【单一日志文件】logs/collation/collation.log。
该文件在每次任务启动时被清空、重复覆盖写（与 deploy 模块的固定路径日志模式一致）：
修复日志为一次性临时输出（仅执行时弹框展示、无需追溯），故不为每个任务单独建文件。
配合 collation_api.collation_stream 的 SSE 从头读取 + tail 推送给前端弹框实时展示。

日志行格式：[时间] [级别] [执行逻辑] [数据源] [数据库] 修复结果
"""
import os
import threading
from datetime import datetime

from core.redis_client import cache_get_json, cache_set_json, cache_delete
from modules.collation.service import (
    TARGET_COLLATION, TARGET_CHARSET,
    get_connection, get_instance_by_id, column_needs_fix, annotate_table,
    fetch_column_issues, build_column_definition,
)

# 任务注册表：{task_key: {status, started_at}}
_collation_tasks = {}
_collation_lock = threading.Lock()
# 任务状态 Redis 镜像 TTL（秒）
TASK_TTL = 86400

# 单一日志文件（所有修复操作共用，每次任务启动时清空覆盖写）
LOG_DIR = os.path.join('logs', 'collation')
COLLATION_LOG_FILE = os.path.join(LOG_DIR, 'collation.log')


def _write_collation_log(level, op, source, database, message):
    """写入一行日志到单一文件：[时间] [级别] [执行逻辑] [数据源] [数据库] 修复结果"""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}] [{op}] [{source}] [{database or '-'}] {message}\n"
    with open(COLLATION_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line)
        f.flush()


def register_task(task_key, lock_name=None):
    """注册一个运行中的任务（进程内 + Redis 镜像，供跨 worker SSE 读取）"""
    payload = {
        'status': 'running',
        'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if lock_name:
        payload['lock'] = lock_name
    with _collation_lock:
        _collation_tasks[task_key] = payload
    cache_set_json(f'task:{task_key}', payload, ttl=TASK_TTL)


def get_task(task_key):
    """获取任务信息（进程内优先，未命中读 Redis 镜像）"""
    with _collation_lock:
        task = _collation_tasks.get(task_key)
        if task:
            return task
    return cache_get_json(f'task:{task_key}')


def _finish_task(task_key, status):
    """更新任务终态（进程内 + Redis 镜像），并释放该任务持有的实例锁"""
    with _collation_lock:
        task = _collation_tasks.get(task_key)
        if task:
            task['status'] = status
        lock_name = task.get('lock') if task else None
    if task:
        cache_set_json(f'task:{task_key}', dict(task), ttl=TASK_TTL)
    else:
        # worker 重启后进程内无记录：读 Redis 镜像补更新并释放锁
        mirror = cache_get_json(f'task:{task_key}') or {}
        mirror['status'] = status
        cache_set_json(f'task:{task_key}', mirror, ttl=TASK_TTL)
        lock_name = mirror.get('lock') or lock_name
    if lock_name:
        cache_delete(lock_name)


def _resolve_source(instance_id):
    """获取数据源名称（实例名），用于日志展示"""
    inst = get_instance_by_id(instance_id)
    if inst and inst.get('name'):
        return inst['name']
    return f'实例{instance_id}'


# ── 后台任务函数（均需在 app_context 内执行，get_connection 依赖查库） ──

def _run_fix_database_task(app, task_key, instance_id, database):
    """修复数据库级默认排序规则（1 条 ALTER DATABASE）"""
    with app.app_context():
        source = _resolve_source(instance_id)
        op = '修复库'
        try:
            _write_collation_log('INFO', op, source, database, f'开始修复数据库默认排序规则 → {TARGET_COLLATION}')
            conn = get_connection(instance_id)
            with conn.cursor() as cursor:
                cursor.execute(
                    f'ALTER DATABASE `{database}` CHARACTER SET '
                    f'{TARGET_CHARSET} COLLATE {TARGET_COLLATION}'
                )
            conn.close()
            _write_collation_log('OK', op, source, database, f'数据库 {database} 修复成功（排序规则 → {TARGET_COLLATION}）')
            _write_collation_log('DONE', op, source, database, '修复完成：成功 1，失败 0，跳过 0')
            _finish_task(task_key, 'completed')
        except Exception as e:
            _write_collation_log('ERROR', op, source, database, f'数据库 {database} 修复失败: {e}')
            _write_collation_log('FAILED', op, source, database, f'修复失败: {e}')
            _finish_task(task_key, 'failed')


def _run_fix_table_task(app, task_key, instance_id, database, table):
    """修复单张表排序规则（1 条 CONVERT TO，同时修复表下异常字段）"""
    with app.app_context():
        source = _resolve_source(instance_id)
        op = '单表修复'
        try:
            conn = get_connection(instance_id, database)
            with conn.cursor() as cursor:
                issues = fetch_column_issues(cursor, database)
                col_count = len(issues.get(table, []))
                tip = f'（含 {col_count} 个异常字段将一并修复）' if col_count else ''
                _write_collation_log('INFO', op, source, database, f'开始修复表 {table} → {TARGET_COLLATION}{tip}')
                cursor.execute(
                    f'ALTER TABLE `{table}` CONVERT TO CHARACTER SET '
                    f'{TARGET_CHARSET} COLLATE {TARGET_COLLATION}'
                )
            conn.close()
            msg = f'{table} 表执行成功'
            if col_count:
                msg += f'，同时修复 {col_count} 个字段'
            _write_collation_log('OK', op, source, database, msg)
            _write_collation_log('DONE', op, source, database, '修复完成：成功 1，失败 0，跳过 0')
            _finish_task(task_key, 'completed')
        except Exception as e:
            _write_collation_log('ERROR', op, source, database, f'{table} 表执行失败: {e}')
            _write_collation_log('FAILED', op, source, database, f'修复失败: {e}')
            _finish_task(task_key, 'failed')


def _run_fix_all_tables_task(app, task_key, instance_id, database, threshold):
    """一键修复所有需修复的表（每张表输出 3 条日志：开始查询 → 阈值判定 → 执行成功；超阈值跳过）"""
    with app.app_context():
        source = _resolve_source(instance_id)
        op = '一键修复'
        ok = fail = skip = 0
        try:
            conn = get_connection(instance_id, database)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TABLE_NAME, TABLE_COLLATION
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
            """, (database,))
            tables = cursor.fetchall()
            issues = fetch_column_issues(cursor, database)
            need_fix = [t for t in tables if annotate_table(t, issues)['need_fix']]
            _write_collation_log('INFO', op, source, database, f'开始一键修复表，共 {len(need_fix)} 张表需修复（阈值 {threshold} 行）')

            if not need_fix:
                _write_collation_log('OK', op, source, database, '所有表已符合要求，无需修复')
                _write_collation_log('DONE', op, source, database, '修复完成：成功 0，失败 0，跳过 0')
                _finish_task(task_key, 'completed')
                conn.close()
                return

            for t in need_fix:
                name = t['TABLE_NAME']
                # 日志 1：开始查询
                _write_collation_log('INFO', op, source, database, f'开始查询 {name} 表')
                try:
                    cursor.execute(f"SELECT COUNT(*) AS cnt FROM `{name}`")
                    row_count = cursor.fetchone()['cnt']
                except Exception:
                    row_count = 0

                if row_count > threshold:
                    # 日志 2：超过阈值 → 跳过
                    skip += 1
                    _write_collation_log('WARN', op, source, database, f'查询结果 {name} 表总行数 {row_count} 条，超过设定阈值 {threshold}，跳过')
                    continue

                # 日志 2：未超过阈值 → 执行
                _write_collation_log('INFO', op, source, database, f'查询结果 {name} 表总行数 {row_count} 条，未超过设定阈值 {threshold}，执行')
                try:
                    cursor.execute(
                        f'ALTER TABLE `{name}` CONVERT TO CHARACTER SET '
                        f'{TARGET_CHARSET} COLLATE {TARGET_COLLATION}'
                    )
                    ok += 1
                    # 日志 3：执行成功
                    _write_collation_log('OK', op, source, database, f'{name} 表执行成功')
                except Exception as err:
                    fail += 1
                    _write_collation_log('ERROR', op, source, database, f'{name} 表执行失败: {err}')
            conn.close()
            _write_collation_log('DONE', op, source, database, f'修复完成：成功 {ok}，失败 {fail}，跳过 {skip}')
            _finish_task(task_key, 'completed')
        except Exception as e:
            _write_collation_log('ERROR', op, source, database, f'批量修复失败: {e}')
            _write_collation_log('FAILED', op, source, database, f'批量修复失败: {e}')
            _finish_task(task_key, 'failed')


def _run_fix_columns_task(app, task_key, instance_id, database, selected, threshold, single_table):
    """修复指定字段（单表指定模式无视阈值；批量模式超阈值表跳过，输出查询/阈值日志）"""
    with app.app_context():
        source = _resolve_source(instance_id)
        op = '单表修复' if single_table else '一键修复'
        ok = fail = skip = 0
        try:
            conn = get_connection(instance_id, database)
            cursor = conn.cursor()
            if single_table:
                _write_collation_log('INFO', op, source, database, f'开始单表修复字段：{single_table}（无视阈值限制）')
            else:
                _write_collation_log('INFO', op, source, database, f'开始一键修复字段（阈值 {threshold} 行，超阈值表跳过）')

            for table_name, col_names in selected.items():
                # 单表指定修复无视阈值；批量修复才做超阈值跳过（输出查询/阈值日志）
                if not single_table:
                    _write_collation_log('INFO', op, source, database, f'开始查询 {table_name} 表')
                    try:
                        cursor.execute(f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
                        row_count = cursor.fetchone()['cnt']
                    except Exception:
                        row_count = 0
                    if row_count > threshold:
                        skip += 1
                        _write_collation_log('WARN', op, source, database, f'查询结果 {table_name} 表总行数 {row_count} 条，超过设定阈值 {threshold}，跳过')
                        continue
                    _write_collation_log('INFO', op, source, database, f'查询结果 {table_name} 表总行数 {row_count} 条，未超过设定阈值 {threshold}，执行')

                cursor.execute("""
                    SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
                           EXTRA, COLUMN_COMMENT, CHARACTER_SET_NAME, COLLATION_NAME
                    FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                """, (database, table_name))
                columns = cursor.fetchall()

                for col in columns:
                    if col['COLUMN_NAME'] not in col_names:
                        continue
                    if not column_needs_fix(col):
                        continue
                    col_name = col['COLUMN_NAME']
                    definition = build_column_definition(col)
                    sql = f"ALTER TABLE `{table_name}` MODIFY COLUMN `{col_name}` {definition}"
                    try:
                        cursor.execute(sql)
                        ok += 1
                        _write_collation_log('OK', op, source, database, f'{table_name} 表字段 {col_name} 修复成功')
                    except Exception as err:
                        fail += 1
                        _write_collation_log('ERROR', op, source, database, f'{table_name} 表字段 {col_name} 修复失败: {err}')
            conn.close()
            _write_collation_log('DONE', op, source, database, f'修复完成：成功 {ok}，失败 {fail}，跳过 {skip}')
            _finish_task(task_key, 'completed')
        except Exception as e:
            _write_collation_log('ERROR', op, source, database, f'字段修复失败: {e}')
            _write_collation_log('FAILED', op, source, database, f'字段修复失败: {e}')
            _finish_task(task_key, 'failed')
