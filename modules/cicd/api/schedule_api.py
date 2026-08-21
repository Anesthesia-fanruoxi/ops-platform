# -*- coding: utf-8 -*-
"""Schedule center API: overview, multiplexed SSE, and schedule logs."""
import json
import time

from flask import Response, stream_with_context

from core.response import success_response
from core.security import require_permission
from core.db import db
from modules.cicd.models import BuildAgent, Build, ScheduleLog
from modules.cicd.services import agent_service


def _overview():
    """组装调度概览：Agent 列表 = MySQL 配置 + Redis 心跳（在线/指标/负载）+ 排队 + 运行中"""
    # 概览缓存 2s：多 SSE 客户端共享一次计算，Redis 不可用时直接计算
    from core.redis_client import cache_get_json, cache_set_json
    cached = cache_get_json('schedule:overview')
    if cached is not None:
        return cached

    agents = BuildAgent.query.order_by(BuildAgent.created_at.desc()).all()
    queue = Build.query.filter_by(status='pending').order_by(Build.created_at.asc()).all()
    running = Build.query.filter_by(status='running').order_by(Build.started_at.desc()).all()
    # 逐 Agent 容错序列化：单个节点数据异常不影响其他节点显示
    agent_list = []
    for a in agents:
        hb = agent_service.get_hb(a)
        try:
            agent_list.append(agent_service.agent_runtime_dict(a, hb))
        except Exception:
            agent_list.append({
                'id': a.id, 'name': a.name, 'host': a.host, 'port': a.port or 9090,
                'status': hb is not None,
                'state': 'stopped' if hb is None else 'idle',
                'disabled': a.disabled or False,
                'install_status': bool(a.install_status),
                'current_load': 0, 'max_concurrent': a.max_concurrent or 1,
            })
    result = {
        'agents': agent_list,
        'queue': [b.to_dict() for b in queue],
        'running': [b.to_dict() for b in running],
    }
    cache_set_json('schedule:overview', result, ttl=2)
    return result


@require_permission('page:cicd_schedule')
def schedule_overview():
    """GET /overview → 调度概览（首屏/兜底）"""
    return success_response(_overview())


def _schedule_logs_snapshot():
    """Return the schedule-log snapshot used by the multiplexed SSE stream."""
    logs = ScheduleLog.query.order_by(ScheduleLog.created_at.desc()).limit(100).all()
    return [log.to_detail_dict() for log in logs]


def _sse_event(event, data):
    """Build a named SSE frame so one connection can carry multiple data types."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@require_permission('page:cicd_schedule')
def schedule_stream():
    """GET /stream?token= -> SSE overview and schedule-log events."""
    def generate():
        last_logs_signature = None
        while True:
            try:
                overview = _overview()
                logs = _schedule_logs_snapshot()
                logs_signature = tuple(
                    (item['id'], item['status'], item['selected_agent'], item['created_at'], item['detail_logs'])
                    for item in logs
                )
                yield _sse_event('overview', overview)
                if logs_signature != last_logs_signature:
                    yield _sse_event('schedule_logs', logs)
                    last_logs_signature = logs_signature
            except Exception as e:
                # Roll back after an exception so the long-lived request does not keep a stale transaction.
                db.session.rollback()
                yield _sse_event('error', {'message': str(e)})
            time.sleep(2)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive',
        },
    )


@require_permission('page:cicd_schedule')
def schedule_log_detail(log_id):
    """GET /logs/<id> → 调度日志详情（含完整日志）"""
    slog = ScheduleLog.query.get(log_id)
    if not slog:
        from core.response import error_response
        return error_response('日志不存在', 404)
    return success_response(slog.to_detail_dict())


@require_permission('page:cicd_schedule')
def schedule_scores():
    """GET /scores → 节点调度评分查询（独立接口，不依赖 SSE/概览缓存）。
    读取 MySQL 配置 + Redis 心跳，计算每个节点的负载评分（越低越优），
    供调度选优参考/排查。"""
    from modules.cicd.services import dispatch_service

    agents = BuildAgent.query.order_by(BuildAgent.created_at.desc()).all()
    result = []
    for a in agents:
        hb = agent_service.get_hb(a)
        online = hb is not None
        rt = agent_service.agent_runtime_dict(a, hb)
        score = dispatch_service.compute_score(a, hb) if online else None
        result.append({
            'id': a.id,
            'name': a.name,
            'host': a.host,
            'online': online,
            'disabled': a.disabled or False,
            'state': rt['state'],
            'install_status': rt['install_status'],
            'current_load': rt['current_load'],
            'max_concurrent': rt['max_concurrent'],
            'cpu_load': rt['cpu_load'],
            'mem_percent': rt['mem_percent'],
            'disk_io_kb': round(rt['disk_read_kb'] + rt['disk_write_kb'], 1),
            'score': round(score, 4) if score is not None else None,
        })
    # 在线且有评分在前，按评分升序（越低越优）；离线排在最后
    result.sort(key=lambda x: (x['score'] is None, x['score'] if x['score'] is not None else 0))
    return success_response(result)
