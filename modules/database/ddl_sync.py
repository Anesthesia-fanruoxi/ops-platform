# -*- coding: utf-8 -*-
"""DDL 自动同步：binlog 监听管理器 + 变更分发执行

设计要点：
- DdlSyncManager 进程内管理「任务×数据源」监听线程；reload() 与 DB 配置增量对齐
  （新任务起线程、删除/暂停/移除源停线程），常驻协调线程每 15s reload 实现配置即时生效
- 多 worker 防重：每个监听先抢 Redis 锁 lock:ddl_sync:{task_id}:{instance_id}
  （TTL 60s，监听线程每 20s 续约；Redis 不可用时不启动监听）
- 监听用 mysql-replication 的 BinLogStreamReader，只看 QUERY_EVENT（同步所有库，自动跳过系统库）；
  首次从当前位点开始（存量差异不动），之后从任务 positions 恢复，每 30s 回写位点
- 分发：CREATE/ALTER/RENAME 转发原始 SQL 到其他勾选源（排除变更源与忽略同步源）；
  DROP/TRUNCATE 不执行，仅记 skipped 日志提示
"""
import json
import logging
import re
import threading
import time

from core.db import db
from modules.database.models import DdlSyncTask, DdlSyncLog
from modules.database.service import get_connection, get_instance_by_id

logger = logging.getLogger(__name__)

# mysql-replication 连接时对 BINLOG_ROW_METADATA 的提示是 logger.warning（每次连接刷屏），
# 且该库不冒泡我们自己的日志格式，统一压到 ERROR 级别
logging.getLogger('pymysqlreplication').setLevel(logging.ERROR)
logging.getLogger('pymysqlreplication.binlogstream').setLevel(logging.ERROR)

# 协调线程 reload 周期（秒）；位点回写周期（秒）
RELOAD_INTERVAL = 15
POSITION_FLUSH_SEC = 30

# 可转发执行的 DDL 动词；DROP/TRUNCATE 只记日志不执行
_SYNCABLE_VERBS = ('CREATE', 'ALTER', 'RENAME')
_SKIP_VERBS = ('DROP', 'TRUNCATE')
_DDL_VERBS = _SYNCABLE_VERBS + _SKIP_VERBS

# 系统库不同步
_SYSTEM_SCHEMAS = frozenset({'mysql', 'information_schema', 'performance_schema', 'sys'})

_DDL_PREFIX_RE = re.compile(r'^\s*(?:/\*.*?\*/\s*|--[^\n]*\n\s*)*', re.S)


def _ddl_type(sql):
    """识别 DDL 动词（CREATE/ALTER/DROP/RENAME/TRUNCATE）；非 DDL 返回空串"""
    head = _DDL_PREFIX_RE.sub('', sql or '', count=1).lstrip().upper()
    for verb in _DDL_VERBS:
        if head.startswith(verb):
            return verb
    return ''


def _server_id(task_id, instance_id):
    """派生 MySQL server_id（同一源上多任务监听需互不相同）"""
    return 1000 + (abs(hash(f'{task_id}:{instance_id}')) % 2000000)


class DdlSyncManager:
    """监听线程管理器（进程内单例）"""

    def __init__(self):
        self._app = None
        self._threads = {}  # {(task_id, instance_id): {'thread':, 'stop': threading.Event()}}
        self._lock = threading.Lock()
        self._coordinator = None

    # ── 启动入口（bootstrap 调用） ──

    def start(self, app):
        if self._coordinator and self._coordinator.is_alive():
            return
        self._app = app
        self._coordinator = threading.Thread(target=self._run_coordinator, daemon=True, name='ddl-sync-coordinator')
        self._coordinator.start()
        logger.info('[DDL同步] 管理器已启动')

    def _run_coordinator(self):
        while True:
            try:
                self.reload()
            except Exception as e:
                logger.warning(f'[DDL同步] reload 异常: {e}')
            time.sleep(RELOAD_INTERVAL)

    # ── 配置对齐 ──

    def reload(self):
        """比对 DB 任务配置，增量启停监听线程"""
        if self._app is None:
            return
        with self._app.app_context():
            expected = set()
            for task in DdlSyncTask.query.filter_by(enabled=True).all():
                for iid in task.source_list():
                    expected.add((task.id, str(iid)))

        with self._lock:
            # 停：配置中已不存在（任务删除/暂停/源移除）
            for key in list(self._threads.keys()):
                if key not in expected:
                    self._threads[key]['stop'].set()
                    del self._threads[key]
            # 起：配置中应有但未运行（含线程已退出）
            for key in expected:
                running = self._threads.get(key)
                if running and running['thread'].is_alive():
                    continue
                stop_flag = threading.Event()
                t = threading.Thread(
                    target=self._listen_source, args=(key[0], key[1], stop_flag),
                    daemon=True, name=f'ddl-sync-{key[0]}-{key[1]}',
                )
                self._threads[key] = {'thread': t, 'stop': stop_flag}
                t.start()

    def status_map(self):
        """{(task_id, instance_id): bool 监听中}（供任务列表展示）"""
        with self._lock:
            return {k: v['thread'].is_alive() for k, v in self._threads.items()}

    # ── 单源监听 ──

    def _listen_source(self, task_id, instance_id, stop_flag):
        """单个「任务×数据源」的 binlog 监听循环（独立线程）
        单实例部署：进程内线程天然唯一，无需分布式锁（Redis 仅作缓存/会话，不参与监听决策）
        """
        try:
            self._listen_loop(task_id, instance_id, stop_flag)
        except Exception as e:
            logger.warning(f'[DDL同步] 任务 {task_id} 源 {instance_id} 监听异常: {e}')

    def _task_snapshot(self, task_id):
        """读取任务最新配置快照"""
        task = DdlSyncTask.query.get(task_id)
        if task is None or not task.enabled:
            return None
        return task

    def _listen_loop(self, task_id, instance_id, stop_flag):
        with self._app.app_context():
            task = self._task_snapshot(task_id)
            positions = task.position_map().get(str(instance_id)) or {} if task else {}
            inst = get_instance_by_id(instance_id)
        if task is None:
            return
        if not inst:
            logger.warning(f'[DDL同步] 任务 {task_id} 源 {instance_id} 不存在，跳过监听')
            return

        try:
            from pymysqlreplication import BinLogStreamReader
            from pymysqlreplication.event import QueryEvent
        except ImportError:
            logger.error('[DDL同步] 缺少依赖 mysql-replication，无法启动 binlog 监听（pip install mysql-replication）')
            return

        # 位点恢复：GTID 优先，其次 file+pos，均无则从当前位点开始（以当前结构为基线）
        kwargs = dict(
            connection_settings={
                'host': inst['host'], 'port': inst['port'],
                'user': inst['user'], 'passwd': inst['password'],
                # 连接超时：避免 binlog 连接建立挂起导致监听线程卡死（失败后由 coordinator reload 重试）
                'connect_timeout': 5,
            },
            server_id=_server_id(task_id, instance_id),
            only_events=[QueryEvent],
            blocking=False,
        )
        if positions.get('gtid'):
            kwargs['auto_position'] = positions['gtid']
        elif positions.get('file'):
            # mysql-replication ≥1.0：resume_stream 传 tuple 不会提取 file/pos（实际从当前位点读），
            # 必须显式传 log_file/log_pos + resume_stream=True 才能从保存位点恢复
            kwargs['log_file'] = positions['file']
            kwargs['log_pos'] = positions.get('pos', 4)
            kwargs['resume_stream'] = True
        else:
            # 无保存位点：从当前位点开始监听（以当前结构为基线），避免重放历史 binlog
            kwargs['resume_stream'] = True

        try:
            stream = BinLogStreamReader(**kwargs)
        except Exception as e:
            # 连接失败：记录后返回，coordinator 下轮 reload 自动重试
            logger.warning(f'[DDL同步] 任务 {task_id} 源 {instance_id} binlog 连接失败: {e}')
            return
        logger.info(f'[DDL同步] 任务 {task_id} 开始监听 {inst["name"]}({inst["host"]}:{inst["port"]}) 全部库（系统库自动跳过）')
        last_flush = time.time()
        pending_pos = None
        err_streak = 0
        try:
            while not stop_flag.is_set():
                try:
                    # mysql-replication ≥1.0 无 __next__，用 fetchone（非阻塞，无事件返回 None）
                    event = stream.fetchone()
                    if event is not None:
                        err_streak = 0  # 恢复后清零连续异常计数
                except Exception:
                    err_streak += 1
                    time.sleep(1)
                    if err_streak >= 30:
                        # 连续异常：保存位点可能已失效（binlog rotate/位置错乱），回退从当前位点重新监听
                        logger.warning(f'[DDL同步] 任务 {task_id} 源 {instance_id} fetchone 连续异常，回退从当前位点监听')
                        return
                    event = None
                if event is not None:
                    pending_pos = {'file': stream.log_file, 'pos': stream.log_pos}
                    if isinstance(event, QueryEvent):
                        try:
                            self._handle_query(task_id, instance_id, event)
                        except Exception as e:
                            # 单条事件处理失败不杀死监听线程：记录后继续，避免反复重启
                            logger.warning(f'[DDL同步] 任务 {task_id} 源 {instance_id} 事件处理异常（已跳过）: {e}')
                # 位点定期回写（避免重启后从过旧位点重放导致 DDL 重复执行）
                if pending_pos and time.time() - last_flush >= POSITION_FLUSH_SEC:
                    last_flush = time.time()
                    try:
                        self._save_position(task_id, instance_id, pending_pos)
                    except Exception as e:
                        logger.warning(f'[DDL同步] 任务 {task_id} 源 {instance_id} 位点回写失败: {e}')
                    pending_pos = None
        finally:
            if pending_pos:
                try:
                    with self._app.app_context():
                        self._save_position(task_id, instance_id, pending_pos)
                except Exception:
                    pass
            stream.close()

    def _save_position(self, task_id, instance_id, pos):
        with self._app.app_context():
            task = DdlSyncTask.query.get(task_id)
            if task is None:
                return
            pmap = task.position_map()
            pmap[str(instance_id)] = pos
            task.positions = json.dumps(pmap, ensure_ascii=False)
            db.session.commit()

    # ── DDL 处理与分发 ──

    def _handle_query(self, task_id, instance_id, event):
        sql = (getattr(event, 'query', '') or '').strip()
        if not sql:
            return
        ddl_type = _ddl_type(sql)
        if not ddl_type:
            return
        schema = getattr(event, 'schema', '') or ''
        if isinstance(schema, bytes):
            schema = schema.decode('utf-8', 'ignore')  # mysql-replication 的 schema 是 bytes
        # 系统库变更不同步；schema 为空的全局语句（如 CREATE DATABASE）照常处理
        if schema.lower() in _SYSTEM_SCHEMAS:
            return
        with self._app.app_context():
            task = self._task_snapshot(task_id)
            if task is None:
                return
            self._dispatch(task, instance_id, ddl_type, schema, sql)

    def _dispatch(self, task, source_id, ddl_type, schema, sql):
        """分发执行：目标 = 勾选源 - 变更源 - 忽略同步源
        一条 DDL 事件写一条日志，targets 列为 JSON 数组（每个目标数据源的执行结果）
        """
        sources = [str(s) for s in task.source_list()]
        ignored = {str(i) for i in task.ignored_list()}
        sql_store = sql[:4096]
        source_name = self._instance_name(source_id)

        if ddl_type in _SKIP_VERBS:
            # 删除/清空类不同步执行，仅记录提示
            self._log(task.id, source_id, schema, ddl_type, sql_store, 'skipped',
                      f'{source_name} 执行了 {ddl_type}，按策略不同步到其他数据源')
            logger.info(f'[DDL同步] 任务 {task.id} {source_name} {ddl_type}（不转发）: {sql_store[:120]}')
            return

        # 目标 = 勾选源 - 变更源自身（忽略源保留在 targets 中，标记 skipped 并说明被忽略）
        targets = [s for s in sources if s != str(source_id)]
        if not targets:
            # 无其余目标（勾选源只剩变更源自身）
            self._log(task.id, source_id, schema, ddl_type, sql_store, 'skipped',
                      '无可分发目标（其他勾选源均被忽略）')
            return
        logger.info(f'[DDL同步] 任务 {task.id} {source_name} 变更分发 → {targets}: {sql_store[:120]}')
        results = []
        for tid in targets:
            tname = self._instance_name(tid)
            if tid in ignored:
                # 被忽略的源：不执行，标记 skipped 并描述原因
                results.append({'id': tid, 'name': tname, 'status': 'skipped',
                                'error': f'{tname} 已被忽略，不同步该源'})
                continue
            status, err = self._execute_on(tid, schema, sql)
            results.append({'id': tid, 'name': tname, 'status': status, 'error': err})
        has_failed = any(r['status'] == 'failed' for r in results)
        executed = [r for r in results if r['status'] != 'skipped']
        if has_failed:
            status = 'failed'
        elif executed:
            status = 'ok'
        else:
            status = 'skipped'
        summary_err = ''
        if has_failed:
            summary_err = '；'.join(
                f"{r['name']}({r['id']}): {r['error'][:200]}" for r in results if r['status'] == 'failed')
        self._log(task.id, source_id, schema, ddl_type, sql_store,
                  status, summary_err, targets=results)

    @staticmethod
    def _execute_on(instance_id, database, sql):
        """在目标数据源执行 DDL（库名取自变更事件 schema；为空则直接执行，如 CREATE DATABASE），返回 (status, error)
        关键：执行前 SET SESSION sql_log_bin=0 —— 分发的 DDL 不写目标库 binlog，
        否则目标库执行会再次触发监听→再分发→目标库再执行……形成「左脚踩右脚」无限循环。
        """
        conn = None
        try:
            conn = get_connection(instance_id)
            with conn.cursor() as cur:
                # 关闭本会话 binlog（get_connection 每次新建连接，不影响其他连接）
                try:
                    cur.execute('SET SESSION sql_log_bin = 0')
                except Exception:
                    pass  # 无权限时降级：可能产生循环分发，至少尽力而为
                if database:
                    # CREATE DATABASE/SCHEMA 的目标库尚不存在，不能先 USE（schema 即新库名）
                    head = sql.lstrip().upper()
                    if not (head.startswith('CREATE DATABASE') or head.startswith('CREATE SCHEMA')):
                        cur.execute(f'USE `{database}`')
                cur.execute(sql)
            conn.commit()
            return 'ok', ''
        except Exception as e:
            return 'failed', str(e)[:2000]
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _instance_name(instance_id):
        inst = get_instance_by_id(instance_id)
        return inst['name'] if inst else str(instance_id)

    @staticmethod
    def _log(task_id, source_id, schema, ddl_type, sql, status, error, targets=None):
        """写一条同步日志；targets 为 [{id, name, status, error}] 数组（每个目标数据源的执行结果）"""
        db.session.add(DdlSyncLog(
            task_id=task_id, source_id=str(source_id), target_id='',
            schema_name=schema, ddl_type=ddl_type, sql_text=sql,
            status=status, error=error or '',
            targets=json.dumps(targets or [], ensure_ascii=False),
        ))
        db.session.commit()


# 进程内单例
ddl_sync_manager = DdlSyncManager()
