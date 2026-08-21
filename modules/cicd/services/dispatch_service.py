# -*- coding: utf-8 -*-
"""
调度服务：推送式任务分发
- assemble_task: 组装完整构建任务体（解密凭据 + Harbor）
- compute_score / pick_best_agent: 评分选优（负载均衡）
- push_task: 加密推送任务到 Agent
- dispatch_pending: 消化 pending 队列，写入调度日志
"""
import logging
import threading
from datetime import datetime

import requests

from core.db import db
from core.redis_client import (
    acquire_lock_mixed, release_lock_mixed, set_if_absent, cache_delete, cache_get,
)
from modules.cicd.models import BuildAgent, Build, ScheduleLog
from modules.cicd.services import build_service
from modules.cicd.services import agent_service
from modules.cicd.services.credential_service import get_decrypted_credential, decrypt_secret
from modules.cicd.services.comm_crypto import encrypt_request_bytes, decrypt_bytes

logger = logging.getLogger(__name__)

# 评分权重（结果越低越优）
W_CAPACITY = 0.4
W_CPU = 0.3
W_MEM = 0.2
W_DISK = 0.1

# 磁盘IO 归一化基准（KB/s），读写合计达到 50MB/s 记为满载
_DISK_BASE_KBS = 51200.0

# 调度串行锁：避免并发心跳/触发重复派发
_dispatch_lock = threading.Lock()


def _harbor_config_from_agent(agent):
    """从 Agent 记录读取 Harbor 凭据（解密密码）"""
    harbor_pass = ''
    if agent.harbor_pass:
        try:
            harbor_pass = decrypt_secret(agent.harbor_pass)
        except Exception:
            harbor_pass = ''
    return {
        'url': agent.harbor_url or '',
        'user': agent.harbor_user or '',
        'pass': harbor_pass,
    }


def _frontend_web_dir(build, agent):
    """前端发布目标：Agent 机 NFS web 挂载根 + 项目/环境/web 子路径。
    例：frontend_mount_dir=/web, 项目 ysh, 环境 test → /web/ysh/test/web
    后端或未配置挂载根返回空（Agent 跳过发布步骤）。
    """
    if build.project_type != 'frontend':
        return ''
    mount_root = (agent.frontend_mount_dir or '').strip().rstrip('/')
    if not mount_root:
        return ''
    proj = build.project.name if build.project else ''
    envn = build.environment.name if build.environment else ''
    return f'{mount_root}/{proj}/{envn}/web'

def _clean_artifact_dirs(value):
    """Normalize service directories so blank entries mean no configured services."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def assemble_task(build, agent):
    """组装下发给 Agent 的完整任务体（凭据仅此刻解密）"""
    # 解析步骤快照
    steps = build.get_steps_snapshot()

    # 解密 Git 凭据
    git_credential = None
    git_credential_id = steps.get('git_credential_id')
    if git_credential_id:
        git_credential = get_decrypted_credential(git_credential_id)

    # 部分构建：下发前将 artifact_dirs 筛成仅选中的服务（按 basename 匹配），
    # Agent 收到的是自包含任务，照常遍历即可，无需感知“选择”逻辑。空=全部
    artifact_dirs = _clean_artifact_dirs(steps.get('artifact_dirs'))
    services = steps.get('services', [])
    if services:
        selected = set(services)
        artifact_dirs = [d for d in artifact_dirs if d.strip().rstrip('/').split('/')[-1] in selected]

    return {
        'build_id': build.id,
        'build_no': build.build_no,
        'project_env': build_service.get_build_work_subdir(build),
        # 镜像命名空间：{项目}-{环境}（不含 type），镜像路径 = {harbor}/{namespace}/{服务}:{tag}
        'image_namespace': build_service.get_build_image_namespace(build),
        'project_type': build.project_type,
        'language': build.language or '',
        'branch': build.branch,
        'steps': {
            'git_docker_image': steps.get('git_docker_image', ''),
            'git_url': steps.get('git_url', ''),
            'git_credential': git_credential,
            'build_docker_image': steps.get('build_docker_image', ''),
            'build_command': steps.get('build_command', ''),
            'artifact_dirs': artifact_dirs,
            'artifact_dir': steps.get('artifact_dir', ''),
            'dockerfile_content': steps.get('dockerfile_content', ''),
            'image_name': steps.get('image_name', ''),
            'image_tag': steps.get('image_tag', ''),
            # 前端发布目标：Agent 机 NFS web 挂载根 + 项目/环境/web 子路径（空=跳过发布步骤）
            # 例：frontend_mount_dir=/web, 项目 ysh, 环境 test → /web/ysh/test/web
            'web_dir': _frontend_web_dir(build, agent),
        },
        'harbor': _harbor_config_from_agent(agent),
        'cancel_requested': build.cancel_requested or False,
        # 重跑起点：正常构建无此字段默认 1（从头执行）；重跑时 >1 表示复用已有目录从该步骤续跑
        'start_step': steps.get('start_step', 1),
        # 构建保留数：Agent 据此清理工作目录旧构建（与 Master 记录保留同步）
        'keep_builds': agent.keep_builds or 5,
    }


def compute_score(agent, hb):
    """
    计算 Agent 负载评分（越低越优）。
    容量比 + CPU + 内存 + 磁盘IO，各归一化到 0~1 后加权。
    """
    load = agent_service._safe_running_count(hb.get('running_count'))
    cap_ratio = load / max(agent.max_concurrent or 1, 1)
    cpu = min(agent_service.to_float(hb.get('cpu_load')) / 100.0, 1.0)
    mem = min(agent_service.to_float(hb.get('mem_percent')) / 100.0, 1.0)
    disk_kbs = agent_service.to_float(hb.get('disk_read_kb')) + agent_service.to_float(hb.get('disk_write_kb'))
    disk = min(disk_kbs / _DISK_BASE_KBS, 1.0)
    return W_CAPACITY * cap_ratio + W_CPU * cpu + W_MEM * mem + W_DISK * disk


def pick_best_agent(logs=None):
    """
    调度选优（结果越低越优）：
    1. 过滤禁用节点（MySQL 配置）
    2. 过滤离线节点（Redis 心跳键不存在）
    3. 过滤 Docker 异常 / 无空闲槽（Redis 心跳字段）
    4. 计算负载评分（Redis 指标）
    5. 返回最优节点
    logs: 可选 list，用于记录决策过程
    """
    all_agents = BuildAgent.query.all()
    if logs is not None:
        logs.append(f'[节点扫描] 共 {len(all_agents)} 个注册节点')

    # 过滤流程
    candidates = []
    for a in all_agents:
        if a.disabled:
            if logs is not None:
                logs.append(f'  ✗ {a.name} → 已禁用，跳过')
            continue
        hb = agent_service.get_hb(a)
        if hb is None:
            if logs is not None:
                logs.append(f'  ✗ {a.name} → 离线，跳过')
            continue
        if hb.get('docker_ok') != '1':
            if logs is not None:
                logs.append(f'  ✗ {a.name} → Docker 异常，跳过')
            continue
        load = agent_service._safe_running_count(hb.get('running_count'))
        if load >= (a.max_concurrent or 1):
            if logs is not None:
                logs.append(f'  ✗ {a.name} → 并发槽已满 ({load}/{a.max_concurrent})，跳过')
            continue
        candidates.append((a, hb))
        if logs is not None:
            logs.append(f'  ✓ {a.name} → 候选')

    if not candidates:
        if logs is not None:
            logs.append('[结果] 无可用节点')
        return None

    # 评分
    if logs is not None:
        logs.append(f'[评分] {len(candidates)} 个候选节点（权重: 容量{W_CAPACITY} CPU{W_CPU} 内存{W_MEM} 磁盘{W_DISK}）')
    scored = []
    for a, hb in candidates:
        load = agent_service._safe_running_count(hb.get('running_count'))
        score = compute_score(a, hb)
        scored.append((score, a, hb))
        if logs is not None:
            logs.append(
                f'  {a.name}: 综合={score:.4f} '
                f'(负载={load}/{a.max_concurrent}, '
                f'CPU={agent_service.to_float(hb.get("cpu_load")):.1f}%, '
                f'内存={agent_service.to_float(hb.get("mem_percent")):.1f}%, '
                f'磁盘IO={agent_service.to_float(hb.get("disk_read_kb"))+agent_service.to_float(hb.get("disk_write_kb")):.0f}KB/s)'
            )

    scored.sort(key=lambda x: x[0])
    best_score, best_agent, _ = scored[0]
    if logs is not None:
        logs.append(f'[选中] {best_agent.name} (评分 {best_score:.4f})')
    return best_agent


def push_task(agent, build, logs=None):
    """
    加密推送任务到 Agent。成功返回 True 并置 build running。
    """
    url = f'http://{agent.host}:{agent.port or 9090}/task'
    if logs is not None:
        logs.append(f'[推送] 目标 {agent.name} ({agent.host}:{agent.port or 9090})')
    try:
        payload = encrypt_request_bytes(assemble_task(build, agent))
        if logs is not None:
            logs.append(f'[推送] 任务体已加密，大小 {len(payload)} bytes')
        resp = requests.post(
            url, data=payload,
            headers={'Content-Type': 'application/json'},
            timeout=15,
        )
        result = decrypt_bytes(resp.content)
        if resp.status_code == 200 and result and result.get('ok'):
            build.status = 'running'
            build.agent_id = agent.id
            build.started_at = datetime.now()
            db.session.commit()
            if logs is not None:
                logs.append(f'[成功] Agent 已接受任务，构建进入 running')
            logger.info(f'[Dispatch] 构建#{build.id} 已派发至 {agent.name}')
            return True
        raise RuntimeError(f'agent 响应无效: {result}')
    except Exception as e:
        if logs is not None:
            logs.append(f'[失败] 推送异常: {e}')
        logger.warning(f'[Dispatch] 推送 {agent.name} 失败: {e}')
        return False


def push_cancel_to_agent(agent, build):
    """尽力推送取消信号到 Agent（即时终止当前运行的容器/进程）。
    best-effort：失败仅记录日志不抛出，由 Agent 步骤边界检查兜底。"""
    url = f'http://{agent.host}:{agent.port or 9090}/cancel'
    try:
        payload = encrypt_request_bytes({'build_id': build.id})
        resp = requests.post(
            url, data=payload,
            headers={'Content-Type': 'application/json'},
            timeout=5,
        )
        result = decrypt_bytes(resp.content)
        ok = resp.status_code == 200 and result and result.get('ok')
        if ok:
            logger.info(f'[Cancel] 构建#{build.id} 取消信号已推送至 {agent.name}')
        else:
            logger.warning(f'[Cancel] 构建#{build.id} 取消信号推送响应异常: {result}')
        return bool(ok)
    except Exception as e:
        logger.warning(f'[Cancel] 推送取消信号到 {agent.name} 失败: {e}')
        return False


def list_agent_dir(agent, path=''):
    """加密请求 Agent 单层列举工作目录（只读、节点侧防越界）；失败返回 (None, error)"""
    url = f'http://{agent.host}:{agent.port or 9090}/list'
    try:
        payload = encrypt_request_bytes({'path': path or ''})
        resp = requests.post(url, data=payload, headers={'Content-Type': 'application/json'}, timeout=5)
        result = decrypt_bytes(resp.content)
        if resp.status_code == 200 and result:
            if result.get('ok'):
                return result.get('entries') or [], ''
            return None, result.get('error') or 'Agent 拒绝请求'
        return None, f'Agent 响应异常 (HTTP {resp.status_code})'
    except Exception as e:
        logger.warning(f'[List] 请求 {agent.name} 目录失败: {e}')
        return None, f'连接 Agent 失败: {e}'


# 调度日志保留条数（独立保留，不随构建记录同步删除）
SCHEDULE_LOG_KEEP = 100


def dispatch_pending():
    """消化 pending 队列：重跑任务优先、新建任务其次，各组按创建时间升序逐个派发。
    无可用节点/节点繁忙时任务保持 pending 挂起，等待下次心跳触发调度。
    跨 worker 用 Redis 分布式锁串行，Redis 不可用降级为进程内锁。"""
    mode, token = acquire_lock_mixed('lock:dispatch', _dispatch_lock, ttl=30000)
    if mode is None:
        return  # 其他 worker 正在调度
    try:
        pending = Build.query.filter_by(status='pending').order_by(Build.created_at.asc()).all()
        # 重跑（已钉住原节点 agent_id 非空）优先，新建（agent_id 为空）其次
        reruns = [b for b in pending if b.agent_id]
        news = [b for b in pending if not b.agent_id]
        for build in reruns + news:
            _dispatch_one(build)
        _cleanup_schedule_logs(SCHEDULE_LOG_KEEP)
    finally:
        release_lock_mixed('lock:dispatch', mode, token, _dispatch_lock)


def _dispatch_one(build):
    """派发单个 pending 构建：同环境串行 + 重跑钉住原节点，新建选最优节点；不可用则挂起等待"""
    logs = []
    # 同环境串行（第 3 条）：同 project_id + environment_id 同时只允许一个构建（Redis 原子锁，
    # 防跨 worker 竞态）；即使存在空闲 Agent 也不派发；前一个完成（成功/失败/取消）后释放锁自动放行
    if build.project_id:
        env_lock = f'lock:env:{build.project_id}:{build.environment_id}'
        # 锁值 = 本构建 build_no（owner），释放时比对防误删他人锁
        if not set_if_absent(env_lock, value=build.build_no, ttl=21600000):
            # 残留锁自愈：owner 构建非活跃（取消/终态/历史 waiting）时清理后重试抢锁
            _reclaim_stale_env_lock(env_lock)
            if not set_if_absent(env_lock, value=build.build_no, ttl=21600000):
                _wait_dispatch(build, logs, '同环境构建进行中，排队等待其完成（同环境串行）', status='same_env')
                return
        build._env_lock = env_lock
    if build.agent_id:
        # 重跑：必须回到原构建节点（构建目录在其磁盘上）
        logs.append(f'[触发] 构建 {build.build_no} 重跑进入调度队列（钉住原节点）')
        agent = BuildAgent.query.get(build.agent_id)
        if not agent or agent.disabled:
            _wait_dispatch(build, logs, '原构建节点已禁用或不存在，等待节点恢复', status='node_down')
            return
        hb = agent_service.get_hb(agent)
        if hb is None:
            _wait_dispatch(build, logs, f'原构建节点 {agent.name} 离线，等待节点上线', status='node_down')
            return
        if hb.get('docker_ok') != '1':
            _wait_dispatch(build, logs, f'原构建节点 {agent.name} Docker 异常，等待恢复', status='node_down')
            return
        load = agent_service._safe_running_count(hb.get('running_count'))
        if load >= (agent.max_concurrent or 1):
            _wait_dispatch(build, logs, f'原构建节点 {agent.name} 并发槽已满 ({load}/{agent.max_concurrent})，排队等待', status='agent_full')
            return
    else:
        # 新建：评分选最优节点
        logs.append(f'[触发] 构建 {build.build_no} 进入调度队列')
        agent = pick_best_agent(logs)
        if not agent:
            _wait_dispatch(build, logs, '无可用节点（无在线节点/Docker 异常/全部繁忙），排队等待', status='agent_full')
            return

    # 跨 worker 原子领取：防并发派发同一构建（Agent poll 领取/其他 worker 已处理则跳过）
    if not set_if_absent(f'build:claim:{build.id}', value=f'dispatch-{agent.name}', ttl=60000):
        # 未领取成功：释放已获取的同环境锁（避免残留）
        _release_env_lock(build)
        return
    ok = push_task(agent, build, logs)
    slog = _active_log(build)
    if ok:
        slog.status = 'dispatched'
        slog.selected_agent = agent.name
    else:
        # 推送失败：保持 pending 挂起，等待下次心跳重试；释放同环境锁（本次未成功持锁）
        _release_env_lock(build)
        logs.append(f'[等待] 推送到 {agent.name} 失败，排队等待重试')
        slog.status = 'no_agent'
    slog.detail_logs = '\n'.join(logs)
    db.session.commit()
    # 无论成败都释放领取标记：成功由 running 状态兜底，失败等待下次重试
    cache_delete(f'build:claim:{build.id}')


def _reclaim_stale_env_lock(env_lock):
    """残留同环境锁自愈：owner 构建不存在或非活跃（非 pending/running）时删除锁（比对 owner 防误删）"""
    try:
        owner = cache_get(env_lock)
    except Exception:
        return
    if not owner:
        return
    owner_build = Build.query.filter_by(build_no=owner).first()
    if owner_build and owner_build.status in ('pending', 'running'):
        return  # owner 确实活跃，正常串行等待
    try:
        if cache_get(env_lock) == owner:
            cache_delete(env_lock)
            logger.warning('[Dispatch] 清理残留同环境锁 %s（owner=%s status=%s）',
                           env_lock, owner, owner_build.status if owner_build else '记录不存在')
    except Exception as e:
        logger.warning('[Dispatch] 清理残留同环境锁失败 %s: %s', env_lock, e)


def _release_env_lock(build):
    """释放同环境锁（比对 owner=build_no，防误删其他构建持有的锁）"""
    key = getattr(build, '_env_lock', None)
    if not key:
        return
    from core.redis_client import cache_get, cache_delete as _cd
    try:
        if cache_get(key) == build.build_no:
            _cd(key)
    except Exception as e:
        logger.warning('[Dispatch] 释放同环境锁失败 %s: %s', key, e)
    build._env_lock = None


def _wait_dispatch(build, logs, reason, status='no_agent'):
    """任务保持 pending 挂起，复用同一条等待态调度日志（防刷屏）。
    status 排队原因分类：same_env=同环境等待 / agent_full=等待Agent释放 / node_down=等待原节点恢复 / no_agent=无节点"""
    # 若已获取同环境锁但本次未能成功派发（node_down/agent_full/推送失败等提前返回路径），必须释放锁，
    # 否则同环境锁残留会阻塞该环境后续所有构建（最长 TTL 6h）
    _release_env_lock(build)
    logs.append(f'[等待] {reason}')
    slog = _active_log(build)
    slog.status = status
    slog.detail_logs = '\n'.join(logs)
    db.session.commit()
    logger.info(f'[Dispatch] 构建#{build.id} 挂起等待：{reason}')


def _active_log(build):
    """获取/创建该构建当前等待态的调度日志：复用 dispatching/no_agent 记录，避免每次心跳新建"""
    slog = ScheduleLog.query.filter(
        ScheduleLog.build_id == build.id,
        ScheduleLog.status.in_(['dispatching', 'no_agent', 'same_env', 'agent_full', 'node_down']),
    ).order_by(ScheduleLog.created_at.desc()).first()
    if not slog:
        slog = ScheduleLog(
            build_id=build.id,
            build_no=build.build_no,
            project_name=build.project.name if build.project else '',
            environment_name=build.environment.name if build.environment else '',
            branch=build.branch,
            triggered_by=build.triggered_by,
            status='dispatching',
        )
        db.session.add(slog)
        db.session.commit()
    return slog


def _cleanup_schedule_logs(keep=SCHEDULE_LOG_KEEP):
    """调度日志独立保留最近 keep 条，超出部分按创建时间删除最旧记录"""
    total = ScheduleLog.query.count()
    if total <= keep:
        return
    stale_ids = [
        r[0] for r in db.session.query(ScheduleLog.id)
        .order_by(ScheduleLog.created_at.desc())
        .offset(keep).all()
    ]
    if stale_ids:
        ScheduleLog.query.filter(ScheduleLog.id.in_(stale_ids)).delete(synchronize_session=False)
        db.session.commit()
        logger.info(f'[Dispatch] 调度日志清理：保留最近 {keep} 条，删除 {len(stale_ids)} 条')
