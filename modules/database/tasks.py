# -*- coding: utf-8 -*-
"""
排序修正异步任务管理 + 后台执行函数

每个修复操作以后台线程执行，逐条 ALTER 写入【单一日志文件】logs/database/database.log。
该文件在每次任务启动时被清空、重复覆盖写（与 deploy 模块的固定路径日志模式一致）：
修复日志为一次性临时输出（仅执行时弹框展示、无需追溯），故不为每个任务单独建文件。
配合 database_api.database_stream 的 SSE 从头读取 + tail 推送给前端弹框实时展示。

日志行格式：[时间] [级别] [执行逻辑] [数据源] [数据库] 修复结果
"""
import os
import threading
from datetime import datetime

from core.redis_client import cache_get_json, cache_set_json, cache_delete
from modules.database.service import (
    TARGET_COLLATION, TARGET_CHARSET,
    get_connection, get_instance_by_id, column_needs_fix, annotate_table,
    fetch_column_issues, build_column_definition,
)
from modules.database.schema_diff import fetch_schema_metadata, compare_schemas

# 任务注册表：{task_key: {status, started_at}}
_collation_tasks = {}
_collation_lock = threading.Lock()
# 任务状态 Redis 镜像 TTL（秒）
TASK_TTL = 86400

# 单一日志文件（所有修复操作共用，每次任务启动时清空覆盖写）
LOG_DIR = os.path.join('logs', 'database')
COLLATION_LOG_FILE = os.path.join(LOG_DIR, 'database.log')


def _write_collation_log(level, op, source, database, message):
    """写入一行日志到单一文件：[时间] [级别] [执行逻辑] [数据源] [数据库] 修复结果"""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}] [{op}] [{source}] [{database or '-'}] {message}\n"
    with open(COLLATION_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line)
        f.flush()


def register_task(task_key, lock_name=None, lock_names=None):
    """注册一个运行中的任务（进程内 + Redis 镜像，供跨 worker SSE 读取）

    lock_names 为多实例锁列表（一源多目标同步）；lock_name 兼容单锁场景。
    """
    payload = {
        'status': 'running',
        'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    locks = list(lock_names) if lock_names else ([lock_name] if lock_name else [])
    if locks:
        payload['locks'] = locks
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
    """更新任务终态（进程内 + Redis 镜像），并释放该任务持有的全部实例锁"""
    with _collation_lock:
        task = _collation_tasks.get(task_key)
        if task:
            task['status'] = status
        locks = list(task.get('locks', [])) if task else []
    if task:
        cache_set_json(f'task:{task_key}', dict(task), ttl=TASK_TTL)
    else:
        # worker 重启后进程内无记录：读 Redis 镜像补更新并释放锁
        mirror = cache_get_json(f'task:{task_key}') or {}
        mirror['status'] = status
        cache_set_json(f'task:{task_key}', mirror, ttl=TASK_TTL)
        locks = list(mirror.get('locks', [])) or locks
    if locks:
        cache_delete(*locks)


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


def _run_sync_structure_task(app, task_key, source_instance_id, source_database, targets):
    """表结构同步：源库 → 一个或多个目标库（一源多目标）

    targets: [{'instance_id': 目标实例, 'database': 目标库, 'tables': 指定对象名列表|None}]
    tables 为指定同步的对象名列表；None 表示同步全部需同步的对象。
    目标多余表/字段/索引/视图/事件一律不删除，仅日志提示。
    """
    with app.app_context():
        source_name = _resolve_source(source_instance_id)
        op = '结构同步'
        total_ok = total_fail = 0
        try:
            _write_collation_log('INFO', op, source_name, source_database,
                                 f'加载源库 {source_name}:{source_database} 元数据，共 {len(targets)} 个目标库待同步')
            src_conn = get_connection(source_instance_id)
            src_meta = fetch_schema_metadata(src_conn, source_database)
            src_conn.close()

            for tgt in targets:
                target_instance_id = tgt['instance_id']
                target_database = tgt.get('database') or source_database
                tables = tgt.get('tables')
                target_name = _resolve_source(target_instance_id)
                source = f'{source_name}→{target_name}'
                ok = fail = 0
                _write_collation_log('INFO', op, source, target_database,
                                     f'── 开始同步目标库 {target_name}:{target_database} ──')
                try:
                    tgt_conn = get_connection(target_instance_id)
                    tgt_meta = fetch_schema_metadata(tgt_conn, target_database)
                    diff = compare_schemas(src_meta, tgt_meta)

                    need_sync = [t for t in diff['tables'] if t['status'] in ('missing', 'diff')]
                    if tables:
                        need_sync = [t for t in need_sync if t['table'] in set(tables)]
                    _write_collation_log('INFO', op, source, target_database,
                                         f'对比完成：共 {len(need_sync)} 个对象需同步，开始执行')

                    if need_sync:
                        cursor = tgt_conn.cursor()
                        for t in need_sync:
                            name = t['table']
                            kind = t.get('object_type', '表')
                            sqls = t['sql'] if isinstance(t['sql'], list) else ([t['sql']] if t['sql'] else [])
                            if t['status'] == 'diff' and kind == '表':
                                detail = f"新建 {len(t['ops']['create'])} / 修改 {len(t['ops']['modify'])} 项，{len(sqls)} 条 SQL"
                            else:
                                detail = f'{len(sqls)} 条 SQL'
                            _write_collation_log('INFO', op, source, target_database,
                                                 f"{'新建' if t['status'] == 'missing' else '变更'}{kind} {name}（{detail}）")
                            for sql in sqls:
                                try:
                                    cursor.execute(sql)
                                    tgt_conn.commit()
                                except Exception as err:
                                    tgt_conn.rollback()
                                    fail += 1
                                    _write_collation_log('ERROR', op, source, target_database,
                                                         f'{name} 执行失败: {err}')
                                    _write_collation_log('WARN', op, source, target_database,
                                                         f'失败 SQL: {sql}')
                                    break
                            else:
                                ok += 1
                                _write_collation_log('OK', op, source, target_database, f'{name} 同步成功')
                    else:
                        _write_collation_log('OK', op, source, target_database, '两侧结构一致（或所选对象无差异），无需同步')
                    tgt_conn.close()

                    extra_tables = [t['table'] for t in diff['tables'] if t['status'] == 'extra']
                    if extra_tables:
                        _write_collation_log('WARN', op, source, target_database,
                                             f'目标库存在 {len(extra_tables)} 个源库没有的对象（未处理）: {", ".join(extra_tables[:10])}')
                    level = 'DONE' if fail == 0 else 'WARN'
                    _write_collation_log(level, op, source, target_database,
                                         f'目标库 {target_name} 同步完成：成功 {ok}，失败 {fail}')
                except Exception as e:
                    fail += 1
                    _write_collation_log('ERROR', op, source, target_database,
                                         f'目标库 {target_name} 同步失败: {e}')
                total_ok += ok
                total_fail += fail

            level = 'DONE' if total_fail == 0 else 'WARN'
            _write_collation_log(level, op, source_name, source_database,
                                 f'全部同步完成：{len(targets)} 个目标库，成功 {total_ok}，失败 {total_fail}')
            _finish_task(task_key, 'completed' if total_fail == 0 else 'failed')
        except Exception as e:
            _write_collation_log('ERROR', op, source_name, source_database, f'结构同步失败: {e}')
            _write_collation_log('FAILED', op, source_name, source_database, f'结构同步失败: {e}')
            _finish_task(task_key, 'failed')
