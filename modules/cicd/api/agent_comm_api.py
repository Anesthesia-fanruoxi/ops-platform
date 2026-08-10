# -*- coding: utf-8 -*-
"""
Agent 通信 API（双向 AES-GCM 加密 + gzip 压缩，白名单放行 /api/cicd/agent/）
协议：register / heartbeat / poll / build step / build result
身份：以 Agent name 标识（去 token），加密认证标签本身即身份凭证
"""
from modules.cicd.services import agent_service
from modules.cicd.services import build_service
from modules.cicd.services.comm_crypto import decrypt_request, encrypt_response
from modules.cicd.models import Build, BuildAgent


def _agent_error(msg, code=400):
    """错误也以加密信封返回，保持协议统一"""
    return encrypt_response({'ok': False, 'error': msg}, code)


# ─── 注册 ─────────────────────────────────────────────────────
def agent_register():
    """POST /register {name, host} → {agent_id}"""
    data = decrypt_request()
    if data is None:
        return _agent_error('报文解密失败（共享密钥不一致？）', 400)
    name = data.get('name', '')
    host = data.get('host', '')
    if not name:
        return _agent_error('name 不能为空')

    agent = agent_service.register_agent_by_name(
        name, host,
        port=data.get('port'),
        docker_ok=bool(data.get('docker_ok', True)),
        version=data.get('version', ''),
        # 现有指标
        cpu_load=data.get('cpu_load'),
        mem_percent=data.get('mem_percent'),
        disk_read_kb=data.get('disk_read_kb'),
        disk_write_kb=data.get('disk_write_kb'),
        # 现有静态配置
        cpu_cores=data.get('cpu_cores'),
        mem_total_gb=data.get('mem_total_gb'),
        disk_total_gb=data.get('disk_total_gb'),
        disk_used_gb=data.get('disk_used_gb'),
        # 新增动态指标
        load1=data.get('load1'),
        load5=data.get('load5'),
        load15=data.get('load15'),
        net_rx_kb=data.get('net_rx_kb'),
        net_tx_kb=data.get('net_tx_kb'),
        disk_percent=data.get('disk_percent'),
        mem_used_gb=data.get('mem_used_gb'),
        mem_avail_gb=data.get('mem_avail_gb'),
        # Docker 构建缓存大小（Agent 本地采集上报）
        docker_cache_size=data.get('docker_cache_size'),
        # 静态系统信息 JSON
        sys_info=data.get('sys_info'),
    )
    return encrypt_response({'ok': True, 'agent_id': agent.id})


# ─── 心跳 ─────────────────────────────────────────────────────
def agent_heartbeat():
    """POST /heartbeat {name, load, docker_ok, version} → {ok}"""
    data = decrypt_request()
    if data is None:
        return _agent_error('报文解密失败', 400)
    name = data.get('name', '')

    agent = agent_service.heartbeat_by_name(
        name,
        docker_ok=bool(data.get('docker_ok', True)),
        version=data.get('version', ''),
        port=data.get('port'),
        # 现有指标
        cpu_load=data.get('cpu_load'),
        mem_percent=data.get('mem_percent'),
        disk_read_kb=data.get('disk_read_kb'),
        disk_write_kb=data.get('disk_write_kb'),
        # 现有静态配置
        cpu_cores=data.get('cpu_cores'),
        mem_total_gb=data.get('mem_total_gb'),
        disk_total_gb=data.get('disk_total_gb'),
        disk_used_gb=data.get('disk_used_gb'),
        # 新增动态指标
        load1=data.get('load1'),
        load5=data.get('load5'),
        load15=data.get('load15'),
        net_rx_kb=data.get('net_rx_kb'),
        net_tx_kb=data.get('net_tx_kb'),
        disk_percent=data.get('disk_percent'),
        mem_used_gb=data.get('mem_used_gb'),
        mem_avail_gb=data.get('mem_avail_gb'),
        # Docker 构建缓存大小（Agent 本地采集上报）
        docker_cache_size=data.get('docker_cache_size'),
        # 静态系统信息 JSON
        sys_info=data.get('sys_info'),
    )
    if not agent:
        return _agent_error('Agent 不存在', 403)
    return encrypt_response({'ok': True})


# ─── 轮询领取构建 ─────────────────────────────────────────────
def agent_poll():
    """
    POST /poll {name} → 有任务返回完整构建配置，无任务返回 {build_id: null}
    Master 在响应时解密凭据 + 读取 Harbor 配置（仅此刻解密），整体加密下发
    """
    data = decrypt_request()
    if data is None:
        return _agent_error('报文解密失败', 400)
    name = data.get('name', '')

    build, reason = agent_service.poll_build_by_name(name)
    if not build:
        if reason == 'invalid_agent':
            return _agent_error('Agent 不存在', 403)
        return encrypt_response({'ok': True, 'build_id': None})

    # 使用 dispatch_service 组装完整任务体
    from modules.cicd.services.dispatch_service import assemble_task
    agent = BuildAgent.query.filter_by(name=name).first()
    if not agent:
        return _agent_error('Agent 不存在', 403)

    task = assemble_task(build, agent)
    task['ok'] = True
    return encrypt_response(task)


# ─── 构建步骤回调 ─────────────────────────────────────────────
def agent_build_step(build_id):
    """POST /build/<id>/step {name, step_no, step_key, status, error?} → 更新步骤状态"""
    data = decrypt_request()
    if data is None:
        return _agent_error('报文解密失败', 400)
    step_no = data.get('step_no')
    status = data.get('status', '')

    build = Build.query.get(build_id)
    if not build:
        return _agent_error('构建不存在', 404)

    if status not in ('running', 'success', 'failed'):
        return _agent_error('status 必须为 running/success/failed')

    # 更新步骤状态文件（SSE 端通过监听 build.json mtime 感知变化）
    build_service.update_step_status(
        build.build_no,
        step_no=int(step_no),
        status=status,
        error=data.get('error', ''),
    )

    # 同步 DB 状态：第一步 running 时更新 build 为 running
    if status == 'running' and build.status == 'pending':
        from datetime import datetime
        build.status = 'running'
        build.started_at = datetime.now()
        from core.db import db as _db
        _db.session.commit()

    return encrypt_response({'ok': True, 'cancel_requested': build.cancel_requested or False})


# ─── 构建结果回调 ─────────────────────────────────────────────
def agent_build_result(build_id):
    """POST /build/<id>/result {name, status, image_digest?, error?} → 落库终态"""
    data = decrypt_request()
    if data is None:
        return _agent_error('报文解密失败', 400)
    status = data.get('status', '')

    if status not in ('success', 'failed'):
        return _agent_error('status 必须为 success 或 failed')

    build = build_service.complete_build(
        build_id,
        status=status,
        image_digest=data.get('image_digest', ''),
        error=data.get('error', ''),
    )
    if not build:
        return _agent_error('构建不存在', 404)

    # 构建成功后自动触发部署（Master 侧改远程 YAML 镜像 tag + kubectl apply，后台线程不阻塞响应）
    if status == 'success':
        from modules.cicd.services.auto_deploy import trigger_auto_deploy
        trigger_auto_deploy(build.id)

    return encrypt_response({'ok': True})


# ─── 内部工具 ─────────────────────────────────────────────────
# (Harbor 配置已迁移到 Agent 记录，由 dispatch_service 统一处理)
