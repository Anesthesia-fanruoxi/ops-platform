# -*- coding: utf-8 -*-
"""
Agent 服务：配置 CRUD + Redis 运行时状态（心跳/负载/指标）

设计：
- MySQL `cicd_agents` 仅存储安装配置（名称/主机/端口/SSH/Harbor/安装状态等）。
- Redis 存储运行时状态：`agent:{id}:hb`（Hash：心跳指标 + 负载），TTL 15s。
- 在线判定：MySQL 中存在配置 且 Redis 心跳键存在 = 在线；仅 MySQL = 离线。
- 调度中心/派发全部读 Redis 心跳，不写数据库动态字段。
"""
import json
import secrets
import threading
import time
from datetime import datetime

from core.db import db
from core.redis_client import (
    cache_delete, cache_get, cache_set, set_if_absent,
    hset_all, hgetall, hincrby, exists,
)
from modules.cicd.models import BuildAgent, Build

# 心跳 TTL（秒）：心跳间隔 5s，TTL 15s，过期即视为离线
HB_TTL = 15
# 服务器 SSH 可达性探测结果缓存 TTL（秒）
SERVER_OK_TTL = 60


def _hb_key(agent_id):
    return f'agent:{agent_id}:hb'


def _server_ok_key(agent_id):
    return f'agent:{agent_id}:server_ok'


def get_hb(agent):
    """读取 Agent 心跳（Redis Hash）；键不存在/Redis 不可用返回 None（离线）"""
    return hgetall(_hb_key(agent.id))


def clear_hb(agent_id):
    """清除 Agent 心跳（卸载/重置/删除时调用，立即离线）"""
    cache_delete(_hb_key(agent_id))


def to_float(value, default=0.0):
    try:
        return float(value) if value not in (None, '') else default
    except (TypeError, ValueError):
        return default


def _hb_metrics(**kw):
    """组装心跳指标（Hash 字段，None 存空串；load 由 Master 维护不在此覆盖）"""
    def s(v):
        return '' if v is None else str(v)

    return {
        'ts': str(time.time()),
        'docker_ok': '1' if kw.get('docker_ok', True) else '0',
        'version': s(kw.get('version')),
        'port': s(kw.get('port')),
        'cpu_load': s(kw.get('cpu_load')),
        'mem_percent': s(kw.get('mem_percent')),
        'disk_read_kb': s(kw.get('disk_read_kb')),
        'disk_write_kb': s(kw.get('disk_write_kb')),
        'cpu_cores': s(kw.get('cpu_cores')),
        'mem_total_gb': s(kw.get('mem_total_gb')),
        'disk_total_gb': s(kw.get('disk_total_gb')),
        'disk_used_gb': s(kw.get('disk_used_gb')),
        'load1': s(kw.get('load1')),
        'load5': s(kw.get('load5')),
        'load15': s(kw.get('load15')),
        'running_count': s(kw.get('running_count')),
        'net_rx_kb': s(kw.get('net_rx_kb')),
        'net_tx_kb': s(kw.get('net_tx_kb')),
        'disk_percent': s(kw.get('disk_percent')),
        'mem_used_gb': s(kw.get('mem_used_gb')),
        'mem_avail_gb': s(kw.get('mem_avail_gb')),
        'docker_cache_size': s(kw.get('docker_cache_size')),
        'sys_info': s(kw.get('sys_info')),
    }


def _write_hb(agent_id, **kw):
    """写心跳到 Redis（并发依据 running_count 由 Agent 自行上报，Master 不维护）"""
    mapping = _hb_metrics(**kw)
    return hset_all(_hb_key(agent_id), mapping, ttl=HB_TTL)


def agent_is_online(agent):
    """在线判定：Redis 心跳键存在即在线（MySQL 有配置为前提）"""
    return hgetall(_hb_key(agent.id)) is not None


def _safe_running_count(value):
    """running_count 服务端钳制：非法（nan/inf/负数/非数字）一律按 0，防恶意/异常 Agent 上报导致崩溃"""
    try:
        v = float(value)
        if v != v or v in (float('inf'), float('-inf')) or v < 0:
            return 0
        return int(v)
    except (TypeError, ValueError):
        return 0


def get_agent_load(agent):
    """读取 Agent 当前运行任务数（Agent 自行上报，Master 并发依据）"""
    data = get_hb(agent)
    return _safe_running_count(data.get('running_count') if data else 0)


def _ensure_server_probe(agent):
    """无心跳的 Agent 需要区分「服务器离线」与「服务停止」：
    后台 SSH 探测一次（结果缓存 60s，探测期间按服务停止处理）。"""
    from flask import current_app
    if not agent.host:
        return
    if set_if_absent(_server_ok_key(agent.id), value='probing', ttl=SERVER_OK_TTL * 1000):
        threading.Thread(
            target=_probe_server_worker,
            args=(current_app._get_current_object(), agent.id),
            daemon=True,
        ).start()


def _probe_server_worker(app, agent_id):
    """后台探测：SSH 能连上 = 服务器在线（服务可能停止）；连不上 = 服务器离线"""
    with app.app_context():
        from modules.cicd.models import BuildAgent
        from modules.cicd.services import install_service
        agent = BuildAgent.query.get(agent_id)
        if not agent or not agent.host:
            return
        try:
            params = {
                'host': agent.host,
                'ssh_port': agent.ssh_port or 22,
                'ssh_username': agent.ssh_username or 'root',
                'auth_type': agent.ssh_auth_type or 'credential',
                'ssh_password': '',
                'credential_id': agent.ssh_credential_id,
            }
            ssh = install_service._connect_ssh(params)
            ssh.close()
            ok = '1'
        except Exception:
            ok = '0'
        cache_set(_server_ok_key(agent_id), ok, ttl=SERVER_OK_TTL)


def agent_runtime_dict(agent, hb):
    """由 MySQL 配置 + Redis 心跳组装调度中心展示数据（字段与前端一致）"""
    online = hb is not None
    load = _safe_running_count(hb.get('running_count') if hb else 0)
    if not online:
        # 无心跳：区分「服务器离线」与「服务停止/已重置」
        server_ok = cache_get(_server_ok_key(agent.id))
        if server_ok is None:
            _ensure_server_probe(agent)
            state = 'stopped'          # 探测期间按可操作处理
        elif server_ok == '0':
            state = 'server_offline'   # SSH 不通：服务器离线，不显示操作按钮
        else:
            state = 'stopped'          # 服务器在线但无心跳：服务停止/已重置
    elif agent.disabled:
        state = 'disabled'
    else:
        state = 'running' if load > 0 else 'idle'

    sys_info = {}
    if hb and hb.get('sys_info'):
        try:
            sys_info = json.loads(hb['sys_info'])
        except (json.JSONDecodeError, TypeError):
            pass

    def r(key, nd=1):
        return round(to_float(hb.get(key) if hb else None), nd)

    last_hb = None
    if hb and hb.get('ts'):
        try:
            last_hb = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(hb['ts'])))
        except (TypeError, ValueError):
            pass

    return {
        'id': agent.id,
        'name': agent.name,
        'host': agent.host,
        'port': agent.port or 9090,
        'status': online,
        'state': state,
        'disabled': agent.disabled or False,
        'install_status': bool(agent.install_status),
        'current_load': load,
        'max_concurrent': agent.max_concurrent or 1,
        # 离线/禁用时 docker 状态未知（不显示 Docker 异常）
        'docker_ok': bool(hb and hb.get('docker_ok') == '1') if online else None,
        'cpu_load': r('cpu_load'),
        'mem_percent': r('mem_percent'),
        'disk_read_kb': r('disk_read_kb'),
        'disk_write_kb': r('disk_write_kb'),
        'cpu_cores': int(to_float(hb.get('cpu_cores') if hb else None)),
        'mem_total_gb': r('mem_total_gb'),
        'disk_total_gb': r('disk_total_gb'),
        'disk_used_gb': r('disk_used_gb'),
        'load1': r('load1', 2),
        'load5': r('load5', 2),
        'load15': r('load15', 2),
        'net_rx_kb': r('net_rx_kb'),
        'net_tx_kb': r('net_tx_kb'),
        'disk_percent': r('disk_percent'),
        'mem_used_gb': r('mem_used_gb'),
        'mem_avail_gb': r('mem_avail_gb'),
        'docker_cache_size': (hb.get('docker_cache_size') if hb else '') or '0B',
        'sys_info': sys_info,
        'last_heartbeat': last_hb,
        'frontend_mount_dir': agent.frontend_mount_dir or '',
    }


# ─── 配置 CRUD（仅 MySQL） ──────────────────────────────────

def generate_token():
    """生成唯一 Agent token"""
    return secrets.token_hex(32)


def create_agent(name, host, max_concurrent=2):
    """创建 Agent 配置记录（未安装/未上线），返回 (agent, token)"""
    token = generate_token()
    agent = BuildAgent(
        name=name,
        host=host,
        token=token,
        max_concurrent=max_concurrent,
    )
    db.session.add(agent)
    db.session.commit()
    return agent, token


def delete_agent(agent_id):
    """删除 Agent（同时清理 Redis 心跳）"""
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return False
    clear_hb(agent.id)
    db.session.delete(agent)
    db.session.commit()
    return True


def get_comm_secret():
    """读取全局 Agent 通讯共享密钥"""
    from modules.system.models import Setting
    s = Setting.query.filter_by(key='agent_comm_secret').first()
    return s.value if s else ''


def register_agent_by_name(name, host, port=None, docker_ok=True, version='',
                           cpu_load=None, mem_percent=None,
                           disk_read_kb=None, disk_write_kb=None,
                           cpu_cores=None, mem_total_gb=None,
                           disk_total_gb=None, disk_used_gb=None,
                           load1=None, load5=None, load15=None,
                           net_rx_kb=None, net_tx_kb=None,
                           disk_percent=None, mem_used_gb=None, mem_avail_gb=None,
                           docker_cache_size=None, sys_info=None, running_count=None):
    """按 name 注册：写 MySQL 配置 + 写 Redis 心跳（在线，负载归零）"""
    agent = BuildAgent.query.filter_by(name=name).first()
    if not agent:
        agent = BuildAgent(
            name=name, host=host, token=generate_token(),
            max_concurrent=2,
        )
        db.session.add(agent)
    else:
        agent.host = host or agent.host
    if port is not None:
        agent.port = port
    db.session.commit()

    _write_hb(
        agent.id,
        port=port, docker_ok=docker_ok, version=version,
        cpu_load=cpu_load, mem_percent=mem_percent,
        disk_read_kb=disk_read_kb, disk_write_kb=disk_write_kb,
        cpu_cores=cpu_cores, mem_total_gb=mem_total_gb,
        disk_total_gb=disk_total_gb, disk_used_gb=disk_used_gb,
        load1=load1, load5=load5, load15=load15,
        net_rx_kb=net_rx_kb, net_tx_kb=net_tx_kb,
        disk_percent=disk_percent, mem_used_gb=mem_used_gb, mem_avail_gb=mem_avail_gb,
        docker_cache_size=docker_cache_size, sys_info=sys_info,
        running_count=running_count,
    )
    return agent


def heartbeat_by_name(name, docker_ok=True, version='',
                      port=None, cpu_load=None, mem_percent=None,
                      disk_read_kb=None, disk_write_kb=None,
                      cpu_cores=None, mem_total_gb=None,
                      disk_total_gb=None, disk_used_gb=None,
                      load1=None, load5=None, load15=None,
                      net_rx_kb=None, net_tx_kb=None,
                      disk_percent=None, mem_used_gb=None, mem_avail_gb=None,
                      docker_cache_size=None, sys_info=None, running_count=None):
    """按 name 处理心跳：仅写 Redis（TTL 15s），不写数据库"""
    agent = BuildAgent.query.filter_by(name=name).first()
    if not agent:
        return None

    _write_hb(
        agent.id,
        port=port, docker_ok=docker_ok, version=version,
        cpu_load=cpu_load, mem_percent=mem_percent,
        disk_read_kb=disk_read_kb, disk_write_kb=disk_write_kb,
        cpu_cores=cpu_cores, mem_total_gb=mem_total_gb,
        disk_total_gb=disk_total_gb, disk_used_gb=disk_used_gb,
        load1=load1, load5=load5, load15=load15,
        net_rx_kb=net_rx_kb, net_tx_kb=net_tx_kb,
        disk_percent=disk_percent, mem_used_gb=mem_used_gb, mem_avail_gb=mem_avail_gb,
        docker_cache_size=docker_cache_size, sys_info=sys_info,
        running_count=running_count,
    )

    # 有空闲容量时触发调度，消化排队任务
    if get_agent_load(agent) < (agent.max_concurrent or 1):
        from modules.cicd.services.dispatch_service import dispatch_pending
        dispatch_pending()
    return agent


def poll_build_by_name(name):
    """按 name 轮询领取构建（负载/领取均走 Redis，跨 worker 原子）"""
    agent = BuildAgent.query.filter_by(name=name).first()
    if not agent:
        return None, 'invalid_agent'
    if not agent_is_online(agent):
        return None, 'offline'
    if get_agent_load(agent) >= (agent.max_concurrent or 1):
        return None, 'busy'

    # 跨 worker 原子领取：逐个尝试 SETNX，防两个 worker 同时派发同一构建
    # 同环境串行（与 dispatch_service._dispatch_one 一致）：同环境已有 running 构建则跳过
    active_env_ids = set()
    for rb in Build.query.filter(Build.status == 'running').all():
        if rb.project_id:
            active_env_ids.add((rb.project_id, rb.environment_id))
    pending = Build.query.filter_by(status='pending').order_by(Build.created_at.asc()).all()
    build = None
    for b in pending:
        if b.project_id and (b.project_id, b.environment_id) in active_env_ids:
            continue  # 同环境构建进行中，排队等待
        # 重跑钉住其他节点的任务不可被本 Agent 领取（构建目录在原节点）
        if b.agent_id and b.agent_id != agent.id:
            continue
        # 同环境串行原子锁：与 _dispatch_one 一致，防跨 worker 竞态双派
        env_lock = f'lock:env:{b.project_id}:{b.environment_id}' if b.project_id else None
        if env_lock and not set_if_absent(env_lock, value=b.build_no, ttl=21600000):
            continue  # 同环境已有构建持锁（进行中），排队等待
        if set_if_absent(f'build:claim:{b.id}', value=f'agent-{agent.id}', ttl=60000):
            build = b
            break
        if env_lock and cache_get(env_lock) == b.build_no:
            cache_delete(env_lock)  # 领取失败：释放本候选的环境锁（owner 比对），继续下一个
    if not build:
        return None, 'no_task'

    build.status = 'running'
    build.agent_id = agent.id
    build.started_at = datetime.now()
    db.session.commit()
    cache_delete(f'build:claim:{build.id}')
    return build, 'ok'
