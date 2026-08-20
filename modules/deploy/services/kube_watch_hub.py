# -*- coding: utf-8 -*-
"""
K8s Watch 共享 Hub：每 namespace 仅一组 watch（Deployment + Pod），多订阅者 fan-out

- 订阅方（SSE 连接）通过 subscribe() 拿到事件队列，帧格式 {'type': 'update'|'error', ...}
- watch 事件到达时仅重建一次快照并广播给全部订阅者（内容去重，避免初始 ADDED 风暴重复推送）
- 无订阅者后延迟 30s 自动停 watch 线程（避免空转）；期内再有订阅直接复用重启
- 单 worker 部署下进程内共享即可（gunicorn -w 1）
"""
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

_IDLE_STOP_SEC = 30    # 无订阅者后多少秒自动停 watch 线程
_WATCH_TIMEOUT = 15    # 单次 watch 超时（到期重建继续监听）
_QUEUE_MAX = 16        # 单订阅者队列上限：满了丢最旧帧（订阅方只关心最新快照）


class _NsHub:
    """单个 namespace 的共享 watch 状态"""

    def __init__(self, namespace, app):
        self.namespace = namespace
        self.app = app  # 供后台 watch 线程推入 app context（K8s 客户端读 DB 配置需要）
        self.lock = threading.Lock()
        self.subscribers = {}          # sid -> queue.Queue
        self.thread = None
        self.stop_flag = threading.Event()
        self.last_active = time.time()
        self._seq = 0

    def subscribe(self):
        """注册订阅者，返回 (sid, 事件队列)；watch 线程不在则拉起"""
        q = queue.Queue(maxsize=_QUEUE_MAX)
        with self.lock:
            self._seq += 1
            self.subscribers[self._seq] = q
            need_start = self.thread is None or not self.thread.is_alive()
            if need_start:
                self.stop_flag.clear()
                self.thread = threading.Thread(
                    target=self._run, name=f'kube-watch-{self.namespace}', daemon=True)
                self.thread.start()
            return self._seq, q

    def unsubscribe(self, sid):
        with self.lock:
            self.subscribers.pop(sid, None)
            self.last_active = time.time()

    def _fanout(self, frame):
        """广播一帧给全部订阅者（队列满则丢最旧，保证最新快照可达）"""
        with self.lock:
            subs = list(self.subscribers.values())
        for q in subs:
            try:
                q.put_nowait(frame)
            except queue.Full:
                try:
                    q.get_nowait()
                    q.put_nowait(frame)
                except Exception:
                    pass

    @staticmethod
    def _close_stream(streams, i):
        try:
            if streams[i] is not None:
                streams[i].close()
        except Exception:
            pass
        streams[i] = None

    def _run(self):
        from modules.deploy.services import kube_client
        namespace = self.namespace
        last_pushed = None
        streams = [None, None]  # [deployment watch, pod watch]
        # K8s 客户端构建/快照读取 DB 配置（k8s_kubeconfig），后台线程必须推入 app context
        with self.app.app_context():
            try:
                while not self.stop_flag.is_set():
                    with self.lock:
                        empty = not self.subscribers
                    # 空闲到期：停线程，等下次订阅重新拉起
                    if empty and time.time() - self.last_active > _IDLE_STOP_SEC:
                        return
                    # watch 流按需（重）建：到期/断开置 None，下轮重建
                    for i in range(2):
                        if streams[i] is None:
                            try:
                                fn = kube_client.watch_deployments if i == 0 else kube_client.watch_pods
                                streams[i] = fn(namespace, timeout_seconds=_WATCH_TIMEOUT)
                            except Exception as e:
                                self._fanout({'type': 'error', 'error': str(e)})
                                return
                    changed = False
                    for i in range(2):
                        try:
                            next(streams[i])
                            changed = True
                        except StopIteration:
                            # 流到期/断开：关闭释放底层连接，下轮重建
                            self._close_stream(streams, i)
                            changed = True
                        except Exception:
                            self._close_stream(streams, i)
                            changed = True
                    # 无订阅者时只消费事件保活，不重建快照（省 CPU / K8s API 调用）
                    if changed and not empty:
                        try:
                            services = kube_client.build_service_snapshot(namespace)
                            if services != last_pushed:
                                last_pushed = services
                                self._fanout({'type': 'update', 'services': services})
                        except Exception:
                            pass
            finally:
                for g in streams:
                    if g is not None:
                        try:
                            g.close()
                        except Exception:
                            pass


# ── 全局注册表 ─────────────────────────────────────────────
_hubs = {}
_hubs_lock = threading.Lock()


def subscribe(namespace):
    """订阅 namespace 服务快照流：返回 (sid, 事件队列)。
    在请求/SSE 上下文内调用，捕获当前 app 供后台 watch 线程使用。"""
    from flask import current_app
    app_obj = current_app._get_current_object()
    with _hubs_lock:
        hub = _hubs.get(namespace)
        if hub is None:
            hub = _hubs[namespace] = _NsHub(namespace, app_obj)
    return hub.subscribe()


def unsubscribe(namespace, sid):
    with _hubs_lock:
        hub = _hubs.get(namespace)
    if hub is not None:
        hub.unsubscribe(sid)
