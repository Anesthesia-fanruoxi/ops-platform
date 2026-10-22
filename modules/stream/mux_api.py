# -*- coding: utf-8 -*-
"""
/api/stream 多路复用端点实现

帧格式：data: {"topic": "<主题名>", ...payload}\n\n
主题名与参数用「:」分隔（namespace/pod/服务名不含冒号），主题之间用「,」分隔：
  monitor                          首页平台健康监控（登录即可）
  svc:<project>:<env>              服务列表（page:service_info）
  log:<project>:<env>:<pod>:<service>:<tail>   Pod 日志（page:service_info）
  builds_env:<environment_id>      单环境构建状态（page:cicd | op:cicd_build）
  builds_envs                      全环境构建状态（page:manage | page:cicd | op:cicd_build）

实现要点：
- 每个主题一个泵线程消费对应 payload 生成器，帧汇入共享队列，主生成器统一写出；
- 主生成器空闲时写 SSE 注释心跳；写失败（客户端断开）→ stop → 各泵线程退出并
  关闭主题生成器（gen.close() 触发其 finally：退订 watch hub / 关闭 K8s 日志流）；
- 主题生成器的空转帧（{'ping': True}）在泵线程丢弃，不下发。
"""
import json
import queue
import threading
import time

from flask import Response, current_app, g, request

from core.response import error_response
from core.security import SUPER_ADMIN_PERMS

_MUX_HEARTBEAT_SECONDS = 20
_QUEUE_MAXSIZE = 5000

# 主题 → 所需权限（None = 登录即可）
_TOPIC_PERMS = {
    'monitor': None,
    'svc': ['page:service_info'],
    'log': ['page:service_info'],
    'builds_env': ['page:cicd', 'op:cicd_build'],
    'builds_envs': ['page:manage', 'page:cicd', 'op:cicd_build'],
}


def _has_perm(user, codes):
    """按 core.security 同源规则校验权限（None/[] 表示登录即可）"""
    if not codes:
        return True
    if not user:
        return False
    if getattr(user, 'is_super_admin', False):
        return any(c in SUPER_ADMIN_PERMS for c in codes)
    return bool(user.role) and any(c in user.role.permissions_list() for c in codes)


def _build_frames(app_obj, parts):
    """按主题构造 payload 生成器；未知主题/参数非法返回 None"""
    kind = parts[0]
    try:
        if kind == 'monitor':
            from modules.system.monitor_api import monitor_frames
            return monitor_frames(app_obj, 5)
        if kind == 'svc' and len(parts) == 3:
            from modules.deploy.api.service_info_stream_api import svc_stream_frames
            return svc_stream_frames(app_obj, parts[1], parts[2])
        if kind == 'builds_env' and len(parts) == 2:
            from modules.cicd.api.build_api import builds_env_frames
            return builds_env_frames(app_obj, int(parts[1]))
        if kind == 'builds_envs':
            from modules.cicd.api.build_api import builds_envs_frames
            return builds_envs_frames(app_obj)
        if kind == 'log' and len(parts) == 6:
            from modules.deploy.api.service_info_api import pod_log_frames
            project, env, pod = parts[1], parts[2], parts[3]
            service, tail = parts[4], max(50, min(int(parts[5]), 5000))
            namespace = f'{project}-{env}-service'
            return pod_log_frames(app_obj, namespace, pod, service, tail)
    except Exception:
        return None
    return None


def mux_stream():
    """SSE 多路复用：一条连接承载多个主题。

    登录即可（全局 token 校验兜底），各主题按 _TOPIC_PERMS 二次校验权限；
    无权限的主题不下发数据，而是推一条 error 帧告知前端。
    """
    topics = [t for t in request.args.get('topics', '').split(',') if t]
    if not topics:
        return error_response('缺少 topics 参数', 400)
    if len(topics) > 8:
        return error_response('topics 数量超限（最多 8 个）', 400)

    user = getattr(g, 'current_user', None)
    from flask import current_app
    app_obj = current_app._get_current_object()

    def generate():
        q = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        stop = threading.Event()
        pumps = []
        alive = set()

        def pump(topic, gen):
            """消费单个主题的 payload 生成器，帧汇入共享队列"""
            try:
                for payload in gen:
                    if stop.is_set():
                        break
                    # 主题自身的空转帧：只用于保持生成器可响应（便于断开时清理），不下发
                    if isinstance(payload, dict) and payload.get('ping'):
                        continue
                    try:
                        q.put((topic, payload), timeout=1)
                    except queue.Full:
                        if stop.is_set():
                            break
            except Exception as e:
                try:
                    q.put_nowait((topic, {'type': 'error', 'error': str(e)[:200]}))
                except Exception:
                    pass
            finally:
                # 生成器此刻必然挂起在 yield 上，close() 会注入 GeneratorExit
                # 触发其 finally（退订 watch hub / 关闭 K8s 日志流 / 归还 DB 连接）
                try:
                    gen.close()
                except Exception:
                    pass
                try:
                    q.put_nowait((topic, None))
                except Exception:
                    pass

        for t in topics:
            parts = t.split(':')
            perm = _TOPIC_PERMS.get(parts[0], [])
            if not _has_perm(user, perm):
                q.put((t, {'type': 'error', 'error': '无权限订阅该主题'}))
                continue
            gen = _build_frames(app_obj, parts)
            if gen is None:
                q.put((t, {'type': 'error', 'error': '未知主题'}))
                continue
            th = threading.Thread(target=pump, args=(t, gen), daemon=True,
                                  name=f'ssemux-{t[:24]}')
            th.start()
            pumps.append(th)
            alive.add(t)

        last_ping = time.time()
        try:
            while True:
                try:
                    item = q.get(timeout=1)
                except queue.Empty:
                    if time.time() - last_ping >= _MUX_HEARTBEAT_SECONDS:
                        last_ping = time.time()
                        yield ': ping\n\n'
                    if not alive:
                        return
                    continue

                topic, payload = item
                if payload is None:
                    # 该主题生成器自然结束（如构建流 5min 空闲自动收尾）
                    alive.discard(topic)
                    if not alive:
                        yield 'data: {"topic": "__end__"}\n\n'
                        return
                    continue

                yield f'data: {json.dumps({"topic": topic, **payload}, ensure_ascii=False)}\n\n'
        finally:
            # 客户端断开：通知所有泵线程退出（各主题生成器的 finally 负责资源清理）
            stop.set()
            for th in pumps:
                th.join(timeout=3)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
