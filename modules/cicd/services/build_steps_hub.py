# -*- coding: utf-8 -*-
"""
构建步骤状态变更事件 hub（进程内 fan-out；gunicorn 单 worker 部署下进程内广播即可）

- 写入端：build_service 步骤状态 / 构建状态变更处调用 publish(build_no) 唤醒订阅者
- 订阅端：步骤 SSE 生成器 subscribe(build_no) 拿事件队列，被唤醒后读 Redis 快照推帧
- 事件只携带唤醒信号，数据统一从 Redis 读，避免事件负载与快照不一致
"""
import queue
import threading
import time

_lock = threading.Lock()
_subscribers = {}  # sid -> (build_no, Queue)
_seq = 0


def subscribe(build_no):
    """注册订阅者，返回 (sid, 事件队列)"""
    global _seq
    q = queue.Queue(maxsize=100)
    with _lock:
        _seq += 1
        sid = _seq
        _subscribers[sid] = (build_no, q)
    return sid, q


def unsubscribe(sid):
    """注销订阅者（SSE 连接断开时调用）"""
    with _lock:
        _subscribers.pop(sid, None)


def publish(build_no):
    """广播构建步骤/状态变更：唤醒订阅该构建的 SSE 连接去读 Redis 推帧。
    队列满则丢弃（订阅者每次唤醒都读全量快照，不依赖事件数量）。"""
    with _lock:
        targets = [q for bn, q in _subscribers.values() if bn == build_no]
    for q in targets:
        try:
            q.put_nowait(time.time())
        except queue.Full:
            pass
