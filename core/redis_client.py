# -*- coding: utf-8 -*-
"""
Redis 客户端统一封装（缓存 / 分布式锁 / 计数 / 集合）

设计原则：
- 所有命令经 safe_* 包装：Redis 异常只记日志并返回 None/False，绝不向业务抛出。
- 快速短路：探测到 Redis 不可用后 5 秒内所有操作直接降级返回，
  避免每次操作都等连接超时拖慢业务（5 秒后自动恢复探测）。
- 缓存采用 Cache-Aside：MySQL 永远是唯一事实源，Redis 仅加速层，未命中回源 DB。
- 锁统一 SET NX PX + Lua 校验释放（防误删他人锁）；Redis 不可用时降级进程内锁。
- 未启用（REDIS_ENABLED=false）时所有调用返回 None/False，业务走原逻辑。
"""
import json
import logging
import threading
import time

from flask import current_app

logger = logging.getLogger(__name__)

_redis_client = None
_client_guard = threading.Lock()
# (可用性, 探测时间戳)：Redis 故障期间避免每次调用都等待连接超时
_client_ok = None
_DOWN_WINDOW = 5  # 故障后快速降级窗口（秒）


def _config(key, default=None):
    # 后台线程（binlog 监听等）无 app context：优先用 init_app 固化的配置
    if key in _CFG:
        return _CFG[key]
    try:
        val = current_app.config.get(key, default)
        if key in _CFG_KEYS:
            _CFG[key] = val  # 有 context 时回写固化，供无 context 线程使用
        return val
    except Exception:
        return _CFG.get(key, default)


_CFG = {}
_CFG_KEYS = ('REDIS_ENABLED', 'REDIS_URL')


def init_app(app):
    """应用初始化时固化 Redis 连接配置（供无 app context 的后台线程使用）"""
    with app.app_context():
        for k in _CFG_KEYS:
            _CFG[k] = app.config.get(k, _CFG.get(k))


def _build_client():
    """创建 Redis 连接池客户端"""
    import redis
    url = _config('REDIS_URL', 'redis://127.0.0.1:6379/0')
    return redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=2,
        socket_connect_timeout=2,
    )


def _mark_down():
    global _client_ok
    _client_ok = (False, time.time())


def _mark_up():
    global _client_ok
    _client_ok = (True, time.time())


def get_redis():
    """返回连接池客户端；未启用或最近 5s 内已知不可用返回 None（快速降级）"""
    global _redis_client
    if not _config('REDIS_ENABLED', True):
        return None
    if _client_ok is not None and not _client_ok[0] and time.time() - _client_ok[1] < _DOWN_WINDOW:
        return None
    if _redis_client is not None:
        return _redis_client
    with _client_guard:
        if _redis_client is not None:
            return _redis_client
        try:
            _redis_client = _build_client()
        except Exception as e:
            logger.warning(f'[Redis] 客户端初始化失败: {e}')
            _redis_client = None
            _mark_down()
        return _redis_client


def is_available():
    """Redis 是否可用（ping 探测；故障后每 5s 自动恢复探测）。未启用返回 False。"""
    if not _config('REDIS_ENABLED', True):
        return False
    now = time.time()
    client = get_redis()
    if client is None:
        if _client_ok is not None and now - _client_ok[1] < _DOWN_WINDOW:
            return False
        # 超过降级窗口：尝试重建连接并 ping（恢复探测）
        try:
            c = _build_client()
            c.ping()
            _redis_client = c
            _mark_up()
            return True
        except Exception:
            _mark_down()
            return False
    if _client_ok is not None and now - _client_ok[1] < 5:
        return _client_ok[0]
    try:
        client.ping()
        _mark_up()
        return True
    except Exception:
        _mark_down()
        logger.warning('[Redis] ping 失败，进入降级模式（业务走原逻辑）')
        return False


def status():
    """健康检查用：返回 disabled / ok / down"""
    if not _config('REDIS_ENABLED', True):
        return 'disabled'
    return 'ok' if is_available() else 'down'


def key(name):
    """拼装带统一前缀的 Redis key"""
    prefix = _config('REDIS_KEY_PREFIX', 'ops:platform:') or ''
    return f'{prefix}{name}'


# ─── 缓存（Cache-Aside） ─────────────────────────────────────

def cache_get(name):
    """读字符串缓存；未命中/Redis 异常返回 None"""
    client = get_redis()
    if client is None:
        return None
    try:
        return client.get(key(name))
    except Exception as e:
        logger.warning(f'[Redis] cache_get {name} 异常: {e}')
        _mark_down()
        return None


def cache_get_json(name, default=None):
    """读 JSON 缓存；未命中/解析失败/异常返回 default"""
    raw = cache_get(name)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def cache_set(name, value, ttl=3600):
    """写字符串缓存；失败静默返回 False"""
    client = get_redis()
    if client is None:
        return False
    try:
        client.set(key(name), value, ex=ttl)
        return True
    except Exception as e:
        logger.warning(f'[Redis] cache_set {name} 异常: {e}')
        _mark_down()
        return False


def cache_set_json(name, value, ttl=3600):
    """写 JSON 缓存（datetime 等自动转字符串）"""
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return False
    return cache_set(name, payload, ttl=ttl)


def cache_delete(*names):
    """删除一个或多个缓存 key；失败静默"""
    client = get_redis()
    if client is None or not names:
        return False
    try:
        client.delete(*[key(n) for n in names])
        return True
    except Exception as e:
        logger.warning(f'[Redis] cache_delete 异常: {e}')
        _mark_down()
        return False


# ─── 计数 / 原子占位 ─────────────────────────────────────────

def increment(name, ttl=900):
    """原子自增并（重新）设置 TTL，用于限流计数；Redis 异常返回 None"""
    client = get_redis()
    if client is None:
        return None
    try:
        k = key(name)
        pipe = client.pipeline()
        pipe.incr(k)
        pipe.expire(k, ttl)
        return pipe.execute()[0]
    except Exception as e:
        logger.warning(f'[Redis] increment {name} 异常: {e}')
        _mark_down()
        return None


def set_if_absent(name, value='1', ttl=60000):
    """SET NX PX：首次设置返回 True，已存在/Redis 异常返回 False（用于锁与原子领取）"""
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.set(key(name), value, nx=True, px=ttl))
    except Exception as e:
        logger.warning(f'[Redis] set_if_absent {name} 异常: {e}')
        _mark_down()
        return False


def expire(name, ttl):
    """重置 key 的 TTL（滑动过期用）；Redis 不可用/键不存在返回 False"""
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.expire(key(name), ttl))
    except Exception as e:
        logger.warning(f'[Redis] expire {name} 异常: {e}')
        _mark_down()
        return False


def sadd(name, *values):
    client = get_redis()
    if client is None:
        return False
    try:
        client.sadd(key(name), *values)
        return True
    except Exception as e:
        logger.warning(f'[Redis] sadd {name} 异常: {e}')
        _mark_down()
        return False


def srem(name, *values):
    client = get_redis()
    if client is None:
        return False
    try:
        client.srem(key(name), *values)
        return True
    except Exception as e:
        logger.warning(f'[Redis] srem {name} 异常: {e}')
        _mark_down()
        return False


def smembers(name):
    """返回集合成员列表；Redis 异常返回 []"""
    client = get_redis()
    if client is None:
        return []
    try:
        return list(client.smembers(key(name)))
    except Exception as e:
        logger.warning(f'[Redis] smembers {name} 异常: {e}')
        _mark_down()
        return []


# ─── Hash（Agent 心跳/负载等运行时状态） ────────────────────

def hset_all(name, mapping, ttl=None):
    """批量写入 Hash 字段并（可选）设置 TTL；失败返回 False"""
    client = get_redis()
    if client is None or not mapping:
        return False
    try:
        k = key(name)
        pipe = client.pipeline()
        pipe.hset(k, mapping=mapping)
        if ttl:
            pipe.expire(k, ttl)
        pipe.execute()
        return True
    except Exception as e:
        logger.warning(f'[Redis] hset_all {name} 异常: {e}')
        _mark_down()
        return False


def hgetall(name):
    """读取 Hash 全部字段；键不存在/Redis 异常返回 None"""
    client = get_redis()
    if client is None:
        return None
    try:
        data = client.hgetall(key(name))
        return data if data else None
    except Exception as e:
        logger.warning(f'[Redis] hgetall {name} 异常: {e}')
        _mark_down()
        return None


def hincrby(name, field, delta):
    """Hash 字段原子增减，返回新值；Redis 异常返回 None"""
    client = get_redis()
    if client is None:
        return None
    try:
        return client.hincrby(key(name), field, delta)
    except Exception as e:
        logger.warning(f'[Redis] hincrby {name}.{field} 异常: {e}')
        _mark_down()
        return None


def exists(name):
    """判断 key 是否存在；Redis 异常返回 False"""
    client = get_redis()
    if client is None:
        return False
    try:
        return bool(client.exists(key(name)))
    except Exception as e:
        logger.warning(f'[Redis] exists {name} 异常: {e}')
        _mark_down()
        return False


# ─── 分布式锁（Redis 优先，降级进程内锁） ────────────────────

_LUA_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


def acquire_lock(name, ttl=30000, owner=None):
    """获取分布式锁：成功返回锁 token，未获取/Redis 异常返回 None"""
    client = get_redis()
    if client is None:
        return None
    token = owner or f'{threading.get_ident()}-{time.time():.6f}'
    try:
        ok = client.set(key(name), token, nx=True, px=ttl)
        return token if ok else None
    except Exception as e:
        logger.warning(f'[Redis] acquire_lock {name} 异常: {e}')
        _mark_down()
        return None


def release_lock(name, token):
    """释放分布式锁：仅当持有者为 token 时删除（Lua 原子操作）"""
    client = get_redis()
    if client is None or not token:
        return False
    try:
        return bool(client.eval(_LUA_RELEASE, 1, key(name), token))
    except Exception as e:
        logger.warning(f'[Redis] release_lock {name} 异常: {e}')
        _mark_down()
        return False


def acquire_lock_mixed(name, local_lock, ttl=30000):
    """优先 Redis 分布式锁，Redis 不可用时降级为进程内锁。
    返回 (mode, token)：mode='redis'/'local' 表示已持有锁；
    获取失败（其他持有者）返回 (None, None)。"""
    if is_available():
        token = acquire_lock(name, ttl=ttl)
        if token is None:
            return None, None
        return 'redis', token
    if not local_lock.acquire(blocking=False):
        return None, None
    return 'local', None


def release_lock_mixed(name, mode, token, local_lock):
    """配合 acquire_lock_mixed 释放锁"""
    if mode == 'redis':
        release_lock(name, token)
    elif mode == 'local':
        try:
            local_lock.release()
        except RuntimeError:
            pass
