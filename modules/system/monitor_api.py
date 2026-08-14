# -*- coding: utf-8 -*-
"""监控信息：SSE 实时推送平台多维度健康检查结果

- 鉴权：require_permission('page:monitor')，EventSource 无法带 Header，token 走 query（core/security 已支持）
- 推送节奏：默认每 5 秒一次（interval 参数可调 2-30 秒）
- 生成器内手动推入 app context（响应返回后请求上下文已 pop，run_checks 内 DB/设置访问需要）
"""
import json
import time

from flask import Response, current_app, request, stream_with_context

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
    """整体健康（状态条）：并行跑全部六维度检查，返回 status/summary"""
    from modules.system.healthz import run_checks
    result = run_checks()
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
    """监控信息 SSE 流：定时推送平台多维度健康检查结果"""
    from modules.system.healthz import run_checks
    app_obj = current_app._get_current_object()
    interval = request.args.get('interval', 5, type=int)
    interval = max(2, min(interval, 30))

    def generate():
        # 生成器懒执行（响应返回后请求上下文已 pop），手动推入 app context
        with app_obj.app_context():
            # 首帧立即推送一次，再按间隔循环
            while True:
                try:
                    result = run_checks()
                    payload = json.dumps({'type': 'health', 'data': result}, ensure_ascii=False)
                except Exception as e:
                    payload = json.dumps({'type': 'error', 'data': {'detail': str(e)[:200]}}, ensure_ascii=False)
                yield f'data: {payload}\n\n'
                time.sleep(interval)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )
