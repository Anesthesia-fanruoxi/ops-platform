# -*- coding: utf-8 -*-
"""监控信息：SSE 实时推送平台多维度健康检查结果

- 鉴权：require_permission('page:monitor')，EventSource 无法带 Header，token 走 query（core/security 已支持）
- 推送节奏：默认每 5 秒一次（interval 参数可调 2-30 秒）
- 生成器内手动推入 app context（响应返回后请求上下文已 pop，run_checks 内 DB/设置访问需要）
"""
import json
import time

from flask import Response, current_app, request

from core.response import success_response
from core.security import require_permission


# ── 首页动态数据接口（dashboard 域）：整体健康 + 单卡检查，登录即可（全局 token 校验兜底） ──

# 单卡检查函数映射（与 healthz.run_checks 并行执行的六维度一致）
MONITOR_CHECKS = {
    'database': None,
    'redis': None,
    'thread_pool': None,
    'task_queue': None,
    'event_loop': None,
    'downstream': None,
}


def _get_check_fn(key):
    if MONITOR_CHECKS.get(key) is None:
        from modules.system import healthz
        MONITOR_CHECKS[key] = getattr(healthz, 'check_' + key, None)
    return MONITOR_CHECKS[key]


def dashboard_monitor_health():
    """整体健康（状态条）：复用缓存的检查结果（TTL 内多请求共享，避免重复全量检查）"""
    from modules.system.healthz import run_checks_cached
    result = run_checks_cached()
    return success_response({
        'status': result['status'],
        'summary': result['summary'],
        'timestamp': result['timestamp'],
        'service': result['service'],
    })


def dashboard_monitor_check(check_key):
    """单卡数据：仅运行该维度检查（比整体更轻量），返回 status/detail/metrics"""
    if check_key not in MONITOR_CHECKS:
        return success_response({'status': 'unknown', 'detail': '未知检查项', 'metrics': {}})
    fn = _get_check_fn(check_key)
    if fn is None:
        return success_response({'status': 'unknown', 'detail': '检查函数缺失', 'metrics': {}})
    from flask import current_app, has_app_context
    try:
        if has_app_context():
            with current_app.app_context():
                data = fn()
        else:
            data = fn()
    except Exception as e:
        data = {'status': 'failed', 'detail': f'检查异常: {e}', 'metrics': {}}
    return success_response(data)


# 首页监控 SSE：登录即可（全局 token 校验兜底），保留供聚合/兼容
def monitor_stream():
    """监控信息 SSE 流：定时推送平台多维度健康检查结果（缓存层：N 个连接共享同一份结果）"""
    from modules.system.healthz import run_checks_cached
    app_obj = current_app._get_current_object()
    interval = request.args.get('interval', 5, type=int)
    interval = max(2, min(interval, 30))

    def generate():
        # 生成器懒执行（响应返回后请求上下文已 pop）。app context 按次收窄：
        # 每轮检查独立推入、结束即 teardown 归还 DB 连接；若整体持有，
        # 每条 SSE 连接会常驻占用连接池，池满后全部 API 排队等连接（P99 飙高）
        while True:
            try:
                with app_obj.app_context():
                    result = run_checks_cached()
                payload = json.dumps({'type': 'health', 'data': result}, ensure_ascii=False)
            except Exception as e:
                payload = json.dumps({'type': 'error', 'data': {'detail': str(e)[:200]}}, ensure_ascii=False)
            yield f'data: {payload}\n\n'
            time.sleep(interval)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )
