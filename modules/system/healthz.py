# -*- coding: utf-8 -*-
"""
平台自身多维度健康检查（/health）

维度映射（Java 运行时概念 → Python 等价物）：
- 线程池 / 协程池     → 进程活跃线程数 + SQLAlchemy 连接池占用（满池 = 无法响应新请求）
- 连接池（DB/Redis）  → SQLAlchemy pool checkedout/overflow + Redis 连接池可用/占用
- 异步队列 / Worker   → 平台异步任务（Agent 安装/卸载等）运行中数量 + 最老任务年龄（积压）
- 事件循环 / 调度延迟 → API 请求耗时滑动窗口 P95/P99（before/after_request 采样，排除流式响应）
- 核心下游依赖       → MySQL / Redis / authPlatform 连通性（服务在线但下游挂 = 调用必报错）

汇总规则：
- 任一核心下游 failed 或资源池 danger → unhealthy（HTTP 503）
- 有 warning → degraded（HTTP 200）
- 全部 ok → healthy（HTTP 200）
"""
import logging
import threading
import time
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# ── API 请求耗时采样（事件循环 / 调度延迟维度） ──────────────
_req_times = deque(maxlen=200)
_req_recent = deque(maxlen=50)  # 最近请求明细（时间/方法/路径/耗时）
_P99_WARN_SEC = 2.0    # P99 超过 2 秒 → warning
_P99_DANGER_SEC = 5.0  # P99 超过 5 秒 → danger

# 线程池维度阈值
_THREAD_WARN = 300    # 活跃线程数 warning
_THREAD_DANGER = 600  # 活跃线程数 danger

# 异步任务积压阈值（秒）
_TASK_WARN_COUNT = 3
_TASK_WARN_AGE = 30 * 60


def register_request_hooks(app):
    """注册请求耗时采样钩子（事件循环维度数据源）"""
    @app.before_request
    def _req_start():
        from flask import request
        request._hz_start = time.monotonic()

    @app.after_request
    def _req_done(resp):
        from flask import request
        start = getattr(request, '_hz_start', None)
        if start is not None:
            dt = time.monotonic() - start
            _req_times.append(dt)
            _req_recent.append({
                'ts': time.strftime('%H:%M:%S'),
                'method': request.method,
                'path': request.path,
                'ms': round(dt * 1000, 1),
            })
        return resp


def _pct(sorted_times, p):
    if not sorted_times:
        return 0.0
    idx = min(len(sorted_times) - 1, int(len(sorted_times) * p))
    return sorted_times[idx]


def _check_result(status, detail, metrics=None):
    return {'status': status, 'detail': detail, 'metrics': metrics or {}}


# ── 各维度检查 ─────────────────────────────────────────────

def check_database():
    """MySQL：Ping 往返 + 连接池占用（池满 = 无法响应新请求）"""
    from sqlalchemy import text
    from core.db import db
    metrics = {'ping_ms': None, 'checkedout': None, 'total': None, 'overflow': None}
    try:
        t0 = time.monotonic()
        db.session.execute(text('SELECT 1'))
        db.session.rollback()
        metrics['ping_ms'] = round((time.monotonic() - t0) * 1000, 1)
        pool = db.engine.pool
        checkedout = pool.checkedout()
        size = pool.size()
        capacity = size + getattr(pool, '_max_overflow', 0)
        metrics.update(checkedout=checkedout, total=capacity, size=size, overflow=pool.overflow())
        if capacity > 0 and checkedout >= capacity:
            return _check_result('danger', f'连接池已满，无法响应新请求（{checkedout}/{capacity}）', metrics)
        if capacity > 0 and checkedout / capacity >= 0.9:
            return _check_result('warning', f'连接池占用偏高（{checkedout}/{capacity}）', metrics)
        return _check_result('ok', f'正常（连接池 {checkedout}/{capacity}，ping {metrics["ping_ms"]}ms）', metrics)
    except Exception as e:
        return _check_result('failed', f'数据库不可用: {e}', metrics)


def check_redis():
    """Redis：Ping + 连接池占用"""
    from core.redis_client import get_redis, status
    st = status()  # 'ok' / 'down' / 'disabled'
    metrics = {'available': None, 'in_use': None}
    if st == 'disabled':
        return _check_result('ok', '未启用（REDIS_ENABLED=false）', metrics)
    if st != 'ok':
        return _check_result('failed', 'Redis 不可用', metrics)
    try:
        pool = get_redis().connection_pool
        metrics['available'] = len(getattr(pool, '_available_connections', []) or [])
        metrics['in_use'] = len(getattr(pool, '_in_use_connections', []) or [])
    except Exception:
        pass
    return _check_result('ok', '正常', metrics)


def _thread_usage(key):
    """按线程名标注用途（对应平台各线程创建点）"""
    if key == 'MainThread':
        return '主程序主线程：Flask 请求处理 / 启动初始化'
    if key.startswith('ThreadPoolExecutor'):
        return '线程池工作线程：健康检查等并行子任务'
    if key == 'ddl-sync-coordinator':
        return 'DDL 同步协调器：定时重载监听任务配置'
    if key.startswith('ddl-sync-'):
        return 'DDL 同步 binlog 监听线程（每任务×数据源一个）'
    return '无名临时线程：部署/构建/Nginx同步等异步任务或 SSE 流连接，结束自动释放'


def check_thread_pool():
    """线程池 / 协程池：进程活跃线程数 + DB 连接池占用（只读，不重复 ping）"""
    from core.db import db
    active = threading.active_count()
    metrics = {'active_threads': active}
    # 线程组成明细 + 用途标注：按名分组，无名临时线程（Thread-N）归并一组
    groups = {}
    for t in threading.enumerate():
        name = t.name or 'Thread'
        if name.startswith('Thread-') or name == 'Thread':
            key = 'Thread-*（临时）'
        elif name.startswith('ThreadPoolExecutor'):
            key = 'ThreadPoolExecutor-*'
        else:
            key = name
        g = groups.setdefault(key, {'name': key, 'count': 0, 'usage': _thread_usage(key)})
        g['count'] += 1
    metrics['threads'] = sorted(groups.values(), key=lambda x: (-x['count'], x['name']))
    status, detail = 'ok', f'活跃线程 {active}'
    try:
        pool = db.engine.pool
        checkedout = pool.checkedout()
        capacity = pool.size() + getattr(pool, '_max_overflow', 0)
        metrics.update(checkedout=checkedout, total=capacity)
        if capacity > 0 and checkedout >= capacity:
            return _check_result('danger', f'DB 连接池已满（{checkedout}/{capacity}），无法响应新请求', metrics)
        if active >= _THREAD_DANGER:
            return _check_result('danger', f'进程活跃线程过多（{active}）', metrics)
        if active >= _THREAD_WARN:
            status, detail = 'warning', f'活跃线程偏多（{active}）'
    except Exception:
        pass
    return _check_result(status, detail, metrics)


def check_task_queue():
    """异步队列 / Worker：运行中异步任务数 + 最老任务年龄（积压检测）"""
    metrics = {'running': 0, 'oldest_age_sec': None}
    try:
        from modules.cicd.services.install_service import _install_tasks
        running = [t for t in _install_tasks.values() if t.get('status') == 'running']
        metrics['running'] = len(running)
        now = time.time()
        # 最老任务年龄：从任务创建时间估算（无创建时间则跳过年龄判断）
        oldest = None
        for t in running:
            events = t.get('events') or []
            if events:
                try:
                    ts = events[0][0] if isinstance(events[0], (list, tuple)) else None
                except Exception:
                    ts = None
                if ts:
                    age = now - ts
                    oldest = age if oldest is None else max(oldest, age)
        if oldest is not None:
            metrics['oldest_age_sec'] = int(oldest)
        if metrics['running'] > _TASK_WARN_COUNT:
            return _check_result('warning', f'运行中异步任务 {metrics["running"]} 个，可能积压', metrics)
        if oldest is not None and oldest > _TASK_WARN_AGE:
            return _check_result('warning', f'最老任务已运行 {int(oldest / 60)} 分钟，疑似卡死', metrics)
        return _check_result('ok', f'运行中 {metrics["running"]} 个', metrics)
    except Exception as e:
        return _check_result('ok', f'任务表不可读（{e}）', metrics)


def check_event_loop():
    """事件循环 / 调度延迟：最近 API 请求耗时 P95/P99"""
    times = sorted(_req_times)
    p95 = _pct(times, 0.95)
    p99 = _pct(times, 0.99)
    metrics = {
        'samples': len(times),
        'p95_ms': round(p95 * 1000, 1),
        'p99_ms': round(p99 * 1000, 1),
    }
    if times:
        metrics['avg_ms'] = round(sum(times) / len(times) * 1000, 1)
        metrics['min_ms'] = round(times[0] * 1000, 1)
        metrics['max_ms'] = round(times[-1] * 1000, 1)
    # 最近请求耗时明细（最新在前，供详情弹窗展示）
    metrics['recent'] = list(_req_recent)[::-1][:30]
    if len(times) < 5:
        return _check_result('ok', '采样不足（<5 请求）', metrics)
    if p99 > _P99_DANGER_SEC:
        return _check_result('danger', f'请求 P99 延迟 {metrics["p99_ms"]}ms，调度卡顿', metrics)
    if p99 > _P99_WARN_SEC:
        return _check_result('warning', f'请求 P99 延迟 {metrics["p99_ms"]}ms', metrics)
    return _check_result('ok', f'P95 {metrics["p95_ms"]}ms / P99 {metrics["p99_ms"]}ms', metrics)


def _http_ping(url, timeout=3):
    """HTTP 探测：任何 HTTP 响应（含 4xx/5xx）视为服务在线；连接失败/超时视为 down"""
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return True, resp.status, round((time.monotonic() - t0) * 1000, 1)
    except urllib.error.HTTPError as e:
        return True, e.code, round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        return False, None, round((time.monotonic() - t0) * 1000, 1)


def check_downstream():
    """核心下游依赖连通性：MySQL / Redis / authPlatform（服务在线但下游挂 = 调用必报错）"""
    from sqlalchemy import text
    from core.db import db
    from core.redis_client import status
    from modules.system.settings_service import get_setting

    items = {}
    # MySQL
    try:
        t0 = time.monotonic()
        db.session.execute(text('SELECT 1'))
        db.session.rollback()
        items['mysql'] = {'status': 'ok', 'ms': round((time.monotonic() - t0) * 1000, 1)}
    except Exception as e:
        items['mysql'] = {'status': 'failed', 'detail': str(e)[:100]}
    # Redis
    st = status()  # 'ok' / 'down' / 'disabled'
    if st == 'disabled':
        items['redis'] = {'status': 'skip', 'detail': 'Redis 未启用'}
    else:
        items['redis'] = {'status': 'ok' if st == 'ok' else 'failed',
                          'detail': None if st == 'ok' else '不可用'}
    # authPlatform（统一鉴权中心，登录代理强依赖）
    base = (get_setting('authplatform_base_url', '') or '').rstrip('/')
    if base:
        ok, code, ms = _http_ping(base + '/health')
        if not ok:
            ok2, code2, ms2 = _http_ping(base + '/')
            ok, code, ms = ok2, code2, ms2
        items['auth_platform'] = {'status': 'ok' if ok else 'failed',
                                  'detail': None if ok else '连接失败（服务可能不在线）',
                                  'ms': ms}
    else:
        items['auth_platform'] = {'status': 'skip', 'detail': '未配置 authplatform_base_url'}

    failed = [k for k, v in items.items() if v.get('status') == 'failed']
    if failed:
        return _check_result('failed', f'核心下游不可用: {", ".join(failed)}', {'items': items})
    return _check_result('ok', '核心下游均可达', {'items': items})


# ── 汇总 ───────────────────────────────────────────────────

def run_checks():
    """并行执行全部维度检查并汇总状态"""
    checks = {}

    from flask import current_app, has_app_context
    app = current_app._get_current_object() if has_app_context() else None

    def _run(name, fn):
        try:
            if app is not None:
                with app.app_context():
                    checks[name] = fn()
            else:
                checks[name] = fn()
        except Exception as e:
            logger.exception('healthz %s 检查异常', name)
            checks[name] = _check_result('failed', f'检查异常: {e}')

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [
            ex.submit(_run, 'database', check_database),
            ex.submit(_run, 'redis', check_redis),
            ex.submit(_run, 'thread_pool', check_thread_pool),
            ex.submit(_run, 'task_queue', check_task_queue),
            ex.submit(_run, 'event_loop', check_event_loop),
            ex.submit(_run, 'downstream', check_downstream),
        ]
        for f in futures:
            f.result()

    # 汇总状态：任一 failed/danger → unhealthy；有 warning → degraded；否则 healthy
    statuses = [c.get('status', 'ok') for c in checks.values()]
    summary = {
        'ok': statuses.count('ok'),
        'warning': statuses.count('warning'),
        'danger': statuses.count('danger'),
        'failed': statuses.count('failed'),
    }
    if 'failed' in statuses or 'danger' in statuses:
        overall = 'unhealthy'
    elif 'warning' in statuses:
        overall = 'degraded'
    else:
        overall = 'healthy'

    return {
        'status': overall,
        'summary': summary,
        'checks': checks,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'service': 'ops-platform',
    }
