# -*- coding: utf-8 -*-
"""
平台自身多维度健康检查（/health）- 采样与入口

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

六维度检查函数与 run_checks 汇总在 healthz_checks.py（本文件 re-export 保持旧引用兼容）。
"""
import threading
import time
from collections import deque

# 兼容旧引用：from modules.system.healthz import run_checks / check_xxx
from modules.system.healthz_checks import (  # noqa: F401
    run_checks,
    check_database, check_redis, check_thread_pool,
    check_task_queue, check_event_loop, check_downstream,
)

# ── API 请求耗时采样（事件循环 / 调度延迟维度） ──────────────
_req_times = deque(maxlen=200)
_req_recent = deque(maxlen=50)  # 最近请求明细（时间/方法/路径/耗时）


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


# ── 缓存层：首页/监控 SSE 等高频轮询复用同一份结果，避免 N 个连接 N 倍重复执行 ──
_cache_lock = threading.Lock()
_cache_result = None
_cache_ts = 0.0
_CACHE_TTL = 4.0  # 秒：略短于 SSE 推送间隔（5s），保证每次推送拿到新数据


def run_checks_cached(ttl=_CACHE_TTL):
    """带 TTL 的 run_checks：命中缓存直接返回；过期时仅一个线程实际执行，其余等待新结果"""
    global _cache_result, _cache_ts
    now = time.monotonic()
    if _cache_result is not None and now - _cache_ts < ttl:
        return _cache_result
    with _cache_lock:
        now = time.monotonic()
        if _cache_result is not None and now - _cache_ts < ttl:
            return _cache_result
        result = run_checks()
        _cache_result, _cache_ts = result, time.monotonic()
        return result
