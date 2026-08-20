# -*- coding: utf-8 -*-
"""调度中心 API：概览 + SSE 实时推送 + 调度日志 + 节点目录浏览"""
import json
import time

from flask import Response, stream_with_context, request

from core.response import success_response, error_response
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


@require_permission('page:cicd')
def schedule_overview():
    """GET /overview → 调度概览（首屏/兜底）"""
    return success_response(_overview())


@require_permission('page:cicd')
def schedule_stream():
    """GET /stream?token= → SSE 每 5s 推送调度概览"""
    def generate():
        while True:
            try:
                payload = json.dumps(_overview(), ensure_ascii=False)
                yield f"data: {payload}\n\n"
            except Exception as e:
                # 异常后必须回滚：否则 SSE 线程的写事务悬挂，
                # 所有 Agent 心跳写入都会被阻塞（曾导致全部节点误判离线）
                db.session.rollback()
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            time.sleep(5)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# ─── 调度日志 ─────────────────────────────────────────
@require_permission('page:cicd')
def schedule_logs():
    """GET /logs → 调度日志列表（基本信息）"""
    logs = ScheduleLog.query.order_by(ScheduleLog.created_at.desc()).limit(100).all()
    return success_response([l.to_dict() for l in logs])


@require_permission('page:cicd')
def schedule_log_detail(log_id):
    """GET /logs/<id> → 调度日志详情（含完整日志）"""
    slog = ScheduleLog.query.get(log_id)
    if not slog:
        from core.response import error_response
        return error_response('日志不存在', 404)
    return success_response(slog.to_detail_dict())


@require_permission('page:cicd')
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


# ─── 节点目录浏览（op:agent_dir，只读、仅工作目录内）─────────────────
@require_permission('op:agent_dir')
def schedule_dirs():
    """GET /dirs?agent_id=&path= → 单层列举 Agent 工作目录（节点侧防越界）"""
    agent_id = request.args.get('agent_id', type=int)
    path = request.args.get('path', '')
    if not agent_id:
        return error_response('缺少 agent_id', 400)
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)
    if agent_service.get_hb(agent) is None:
        return error_response('Agent 离线，无法浏览目录', 400)

    from modules.cicd.services import dispatch_service
    entries, err = dispatch_service.list_agent_dir(agent, path)
    if err:
        return error_response(err, 502)
    return success_response({'entries': entries, 'path': path})
