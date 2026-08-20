# -*- coding: utf-8 -*-
"""
服务信息 SSE 实时流 + 环境变量接口（阶段二）

- /service-info/stream：先推全量快照，再订阅 kube_watch_hub 共享 watch（每 namespace 仅一组
  Deployment + Pod watch，多连接 fan-out），30s 心跳保活；K8s 不可用时推 error 事件并关闭
- /service-info/envs：环境变量弹窗打开时实时读 K8s Deployment spec（不随列表/SSE 携带）

复用 pod_log_stream 模式：app_context 手动推入、token 走 query 参数、X-Accel-Buffering: no
"""
import json
import queue
import time

from flask import request, Response

from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.services import kube_client, kube_watch_hub


def _sse(data, event=None):
    """序列化一条 SSE 事件"""
    prefix = f'event: {event}\n' if event else ''
    return prefix + 'data: ' + json.dumps(data, ensure_ascii=False) + '\n\n'


@require_permission('page:service_info')
def service_info_stream():
    """服务卡片 SSE 流：快照 → 订阅共享 watch hub → 心跳；K8s 不可用推 error 后关闭"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    if not project or not env:
        return error_response('缺少参数 project / env', 400)
    namespace = f'{project}-{env}-service'

    from flask import current_app
    app_obj = current_app._get_current_object()

    def generate():
        with app_obj.app_context():
            # 全量快照先行（前端首屏直接可用）
            try:
                services = kube_client.build_service_snapshot(namespace)
                yield _sse({'type': 'snapshot', 'services': services})
            except Exception as e:
                yield _sse({'type': 'error', 'error': str(e)})
                return

            # 订阅共享 hub（同 namespace 多连接共用一组 K8s watch）
            sid, q = kube_watch_hub.subscribe(namespace)
            last_heartbeat = time.time()
            try:
                while True:
                    try:
                        frame = q.get(timeout=1)
                    except queue.Empty:
                        frame = None
                    if frame is not None:
                        if frame.get('type') == 'error':
                            yield _sse(frame)
                            return
                        yield _sse(frame)
                    if time.time() - last_heartbeat >= 30:
                        last_heartbeat = time.time()
                        yield _sse({'type': 'heartbeat', 'ts': int(time.time())})
            except GeneratorExit:
                return
            finally:
                kube_watch_hub.unsubscribe(namespace, sid)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@require_permission('page:service_info')
def service_envs():
    """实时读取服务 Deployment spec 环境变量（弹窗打开时调用，K8s 不可用返回 502）"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    service = request.args.get('service', '')
    if not project or not env or not service:
        return error_response('缺少参数 project / env / service', 400)
    namespace = f'{project}-{env}-service'
    try:
        for d in kube_client.list_deployments(namespace):
            if d['name'] == service:
                return success_response({'envs': d['envs'], 'namespace': namespace})
    except Exception as e:
        return error_response(str(e), 502)
    return success_response({'envs': [], 'namespace': namespace})
