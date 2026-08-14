# -*- coding: utf-8 -*-
"""
服务信息 SSE 实时流 + 环境变量接口（阶段二）

- /service-info/stream：先推全量快照，再按 K8s Watch（Deployment + Pod）事件重建快照增量推送，
  30s 心跳保活；K8s 不可用时推 error 事件并关闭，前端回退 HTTP list
- /service-info/envs：环境变量弹窗打开时实时读 K8s Deployment spec（不随列表/SSE 携带）

复用 pod_log_stream 模式：app_context 手动推入、token 走 query 参数、X-Accel-Buffering: no
"""
import json
import time

from flask import request, Response

from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.services import kube_client


def _sse(data, event=None):
    """序列化一条 SSE 事件"""
    prefix = f'event: {event}\n' if event else ''
    return prefix + 'data: ' + json.dumps(data, ensure_ascii=False) + '\n\n'


@require_permission('page:service_info')
def service_info_stream():
    """服务卡片 SSE 流：快照 → watch 增量 → 心跳；K8s 不可用推 error 后关闭"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    if not project or not env:
        return error_response('缺少参数 project / env', 400)
    namespace = f'{project}-{env}-service'

    from flask import current_app
    app_obj = current_app._get_current_object()

    def generate():
        with app_obj.app_context():
            streams = [None, None]  # [deployment watch, pod watch]
            last_pushed = None      # 上次推送的服务快照（内容去重，避免初始 ADDED 风暴重复推送）
            try:
                # 全量快照先行（前端首屏直接可用）
                services = kube_client.build_service_snapshot(namespace)
                yield _sse({'type': 'snapshot', 'services': services})
                last_pushed = services
            except Exception as e:
                yield _sse({'type': 'error', 'error': str(e)})
                return

            streams = [
                kube_client.watch_deployments(namespace, timeout_seconds=15),
                kube_client.watch_pods(namespace, timeout_seconds=15),
            ]
            last_heartbeat = time.time()
            try:
                while True:
                    changed = False
                    for i in range(2):
                        try:
                            next(streams[i])
                            changed = True
                        except StopIteration:
                            # 流到期/断开：关闭并重建（自动取最新 resourceVersion 继续监听）
                            try:
                                streams[i].close()
                            except Exception:
                                pass
                            try:
                                fn = kube_client.watch_deployments if i == 0 else kube_client.watch_pods
                                streams[i] = fn(namespace, timeout_seconds=15)
                                changed = True
                            except Exception:
                                pass
                        except GeneratorExit:
                            raise
                        except Exception:
                            changed = True
                    if changed:
                        try:
                            services = kube_client.build_service_snapshot(namespace)
                            if services != last_pushed:
                                last_pushed = services
                                yield _sse({'type': 'update', 'services': services})
                        except Exception:
                            pass
                    if time.time() - last_heartbeat >= 30:
                        last_heartbeat = time.time()
                        yield _sse({'type': 'heartbeat', 'ts': int(time.time())})
            except GeneratorExit:
                return
            except Exception as e:
                try:
                    yield _sse({'type': 'error', 'error': str(e)})
                except Exception:
                    pass
            finally:
                for g in streams:
                    if g is not None:
                        try:
                            g.close()
                        except Exception:
                            pass

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
