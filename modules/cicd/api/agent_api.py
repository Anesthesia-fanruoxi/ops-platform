# -*- coding: utf-8 -*-
"""Agent 管理 API（管理员操作 + 调度中心日志代理）"""
import json
import time

import requests as http_requests
from flask import request, Response, stream_with_context, current_app

from core.response import success_response, error_response
from core.security import require_permission, require_any_permission
from core.db import db
from modules.cicd.models import BuildAgent
from modules.cicd.services import agent_service
from modules.cicd.services import install_service


def _norm_dir(v):
    """规范化目录输入：去首尾空白 + 去尾部斜杠（支持带/不带 / 两种写法，避免拼接时 //）"""
    return (v or '').strip().rstrip('/')



@require_permission('page:cicd_schedule')
def proxy_agent_log(agent_id):
    """
    Agent 日志代理：转发到 Agent 的 /agentlog 接口
    GET /api/cicd/agents/<id>/log?follow=true&token=
    follow=true → SSE 流式实时；否则一次性返回全文
    """
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)
    if not agent.host:
        return error_response('Agent 无主机地址', 400)

    follow = request.args.get('follow', 'false')
    agent_url = f'http://{agent.host}:{agent.port or 9090}/agentlog?follow={follow}'

    if follow == 'true':
        def generate():
            try:
                resp = http_requests.get(agent_url, stream=True, timeout=(5, 300))
                for chunk in resp.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
            except Exception as e:
                yield f'data: {{"error": "{str(e)}"}}\n\n'

        return Response(
            stream_with_context(generate()),
            content_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
        )

    # 一次性返回全文
    try:
        resp = http_requests.get(agent_url, timeout=10)
        return Response(resp.content, content_type='text/plain; charset=utf-8')
    except Exception as e:
        return error_response(f'Agent 日志获取失败: {e}', 502)


@require_permission('page:cicd_schedule')  # 查看类：Agent 列表归属调度中心查看权限
def list_agents():
    """Agent 列表（MySQL 配置 + Redis 运行时状态）"""
    agents = BuildAgent.query.order_by(BuildAgent.created_at.desc()).all()
    result = []
    for a in agents:
        hb = agent_service.get_hb(a)
        rt = agent_service.agent_runtime_dict(a, hb)
        d = a.to_dict()
        d['status'] = rt['status']
        d['current_load'] = rt['current_load']
        d['docker_ok'] = rt['docker_ok']
        d['last_heartbeat'] = rt['last_heartbeat']
        result.append(d)
    return success_response(result)


@require_permission('page:cicd_schedule')  # 查看类：Agent 详情归属调度中心查看权限
def get_agent_detail(agent_id):
    """Agent 详情（安装/重装回填用）"""
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)
    return success_response(agent.to_detail_dict())


@require_permission('op:agent')
def install_agent():
    """
    创建 Agent 记录并返回全局通讯共享密钥
    Agent 凭 name + 共享密钥（环境变量 CICD_COMM_SECRET）即可加密注册上线
    """
    data = request.json
    name = data.get('name', '').strip()
    host = data.get('host', '').strip()
    if not name:
        return error_response('Agent 名称不能为空', 400)
    if BuildAgent.query.filter_by(name=name).first():
        return error_response('Agent 名称已存在', 400)

    max_concurrent = 1
    agent, _ = agent_service.create_agent(name, host, max_concurrent)
    return success_response({
        'agent': agent.to_dict(),
        'comm_secret': agent_service.get_comm_secret(),
        'hint': '请将共享密钥配置到 Agent 环境变量 CICD_COMM_SECRET，Agent 启动后凭名称自动加密注册上线',
    }, 'Agent 创建成功')


@require_permission('op:agent')
def install_agent_remote():
    """
    远程安装 Agent（POST）：创建 DB 记录 + 启动后台 SSH 安装任务
    返回 task_id 供 SSE 订阅
    """
    data = request.json
    name = data.get('name', '').strip()
    host = data.get('host', '').strip()
    if not name:
        return error_response('Agent 名称不能为空', 400)
    if not host:
        return error_response('主机地址不能为空', 400)
    if BuildAgent.query.filter_by(name=name).first():
        return error_response('Agent 名称已存在', 400)

    ssh_password = data.get('ssh_password', '')
    credential_id = data.get('credential_id')
    auth_type = data.get('auth_type', 'password')
    if auth_type == 'password' and not ssh_password:
        return error_response('SSH 密码不能为空', 400)
    if auth_type in ('credential', 'ssh_key') and not credential_id:
        return error_response('请选择凭据', 400)

    # 创建 DB 记录（installing 状态，并发固定为 1）
    agent, _ = agent_service.create_agent(name, host, 1)

    # 保存 SSH 连接信息（重置/卸载复用）
    agent.ssh_port = int(data.get('ssh_port', 22))
    agent.ssh_username = data.get('ssh_username', 'root')
    agent.ssh_auth_type = auth_type
    agent.ssh_credential_id = credential_id
    agent.work_dir = data.get('work_dir', '/data/cicd').strip() or '/data/cicd'
    agent.keep_builds = int(data.get('keep_builds', 5) or 5)
    agent.frontend_mount_dir = _norm_dir(data.get('frontend_mount_dir'))
    agent.nfs_server = (data.get('nfs_server') or '').strip()
    agent.nfs_share = _norm_dir(data.get('nfs_share'))
    db.session.commit()

    # Harbor：地址从表单取，账号密码从凭据取
    harbor_credential_id = data.get('harbor_credential_id')
    harbor_type = data.get('harbor_type', 'public').strip()
    harbor_ip = data.get('harbor_ip', '').strip()
    harbor_url = data.get('harbor_url', '').strip()
    if not harbor_url:
        return error_response('请填写 Harbor 地址', 400)
    if not harbor_credential_id:
        return error_response('请选择 Harbor 凭据', 400)
    from modules.cicd.models import GitCredential
    from modules.cicd.services.credential_service import decrypt_secret
    hcred = GitCredential.query.get(int(harbor_credential_id))
    if not hcred:
        return error_response('Harbor 凭据不存在', 400)
    harbor_user = hcred.username or ''
    harbor_pass = decrypt_secret(hcred.secret) if hcred.secret else ''
    agent.harbor_type = harbor_type
    agent.harbor_url = harbor_url
    agent.harbor_user = harbor_user
    agent.harbor_credential_id = int(harbor_credential_id)
    agent.harbor_ip = harbor_ip if harbor_type == 'private' else ''
    db.session.commit()

    # 组装安装参数
    master_url = data.get('master_url', '').strip()
    if not master_url:
        # 自动推断：用当前请求的 host
        master_url = request.host_url.rstrip('/')
    agent.master_url = master_url
    db.session.commit()

    params = {
        'name': name,
        'host': host,
        'ssh_port': int(data.get('ssh_port', 22)),
        'ssh_username': data.get('ssh_username', 'root'),
        'auth_type': auth_type,
        'ssh_password': ssh_password,
        'credential_id': credential_id,
        'master_url': master_url,
        'work_dir': data.get('work_dir', '/data/cicd').strip() or '/data/cicd',
        'frontend_mount_dir': (data.get('frontend_mount_dir') or '').strip(),
        'nfs_server': (data.get('nfs_server') or '').strip(),
        'nfs_share': (data.get('nfs_share') or '').strip(),
        'comm_secret': agent_service.get_comm_secret(),
        'install_docker': data.get('install_docker', False),
        'harbor_ip': harbor_ip,
        'harbor_url': harbor_url,
        'harbor_user': harbor_user,
        'harbor_pass': harbor_pass,
        'agent_id': agent.id,
    }

    task_id = install_service.create_install_task(params)
    return success_response({'task_id': task_id, 'agent_id': agent.id}, '安装任务已启动')


@require_permission('op:agent')
def install_agent_stream(task_id):
    """SSE 流式推送安装进度"""
    def generate():
        sent = 0
        idle_count = 0
        while True:
            task = install_service.get_install_task(task_id)
            if not task:
                yield f"data: {json.dumps({'status': 'failed', 'message': '任务不存在'})}\n\n"
                return

            events = task['events']
            while sent < len(events):
                evt = events[sent]
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                sent += 1

            if task['status'] in ('done', 'failed'):
                # 发完剩余事件后结束
                while sent < len(task['events']):
                    evt = task['events'][sent]
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                    sent += 1
                yield f"data: {json.dumps({'status': task['status'], 'done': True})}\n\n"
                return

            idle_count += 1
            if idle_count > 300:  # 5分钟超时
                yield f"data: {json.dumps({'status': 'failed', 'message': '安装超时'})}\n\n"
                return
            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@require_permission('op:agent')
def delete_agent(agent_id):
    """删除 Agent"""
    ok = agent_service.delete_agent(agent_id)
    if not ok:
        return error_response('Agent 不存在', 404)
    return success_response(msg='删除成功')


@require_permission('op:agent')
def reinstall_agent(agent_id):
    """
    重新安装 Agent（POST）：对“待安装”状态的 Agent 重新执行远程安装
    SSH 连接信息从 DB 读取，前端可传 master_url / install_docker / harbor 等可编辑字段
    """
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)
    if agent_service.agent_is_online(agent):
        return error_response('该 Agent 已在线（已安装），无需重复安装', 400)

    data = request.json or {}
    # 凭据支持变更：前端传了用前端的，否则用 DB 已保存的
    auth_type = data.get('auth_type', '').strip() or agent.ssh_auth_type or 'credential'
    credential_id = data.get('credential_id') or agent.ssh_credential_id
    ssh_password = data.get('ssh_password', '')
    ssh_username = data.get('ssh_username', '').strip() or agent.ssh_username or 'root'
    if auth_type in ('credential', 'ssh_key') and not credential_id:
        return error_response('请选择凭据', 400)

    # 保存变更后的凭据信息
    agent.ssh_auth_type = auth_type
    agent.ssh_credential_id = credential_id
    agent.ssh_username = ssh_username

    # Master 地址：前端传了用前端的，否则用已保存的
    master_url = data.get('master_url', '').strip() or agent.master_url or ''
    if not master_url:
        master_url = request.host_url.rstrip('/')
    agent.master_url = master_url

    # Harbor：地址从表单取（或已保存的），账号密码从凭据取
    harbor_credential_id = data.get('harbor_credential_id') or agent.harbor_credential_id
    harbor_type = data.get('harbor_type', '').strip() or agent.harbor_type or 'public'
    harbor_ip = data.get('harbor_ip', '').strip() if data.get('harbor_ip') is not None else (agent.harbor_ip or '')
    harbor_url = data.get('harbor_url', '').strip() or agent.harbor_url or ''
    if not harbor_url:
        return error_response('请填写 Harbor 地址', 400)
    if not harbor_credential_id:
        return error_response('请选择 Harbor 凭据', 400)
    from modules.cicd.models import GitCredential
    from modules.cicd.services.credential_service import decrypt_secret
    hcred = GitCredential.query.get(int(harbor_credential_id))
    if not hcred:
        return error_response('Harbor 凭据不存在', 400)
    harbor_user = hcred.username or ''
    harbor_pass_plain = decrypt_secret(hcred.secret) if hcred.secret else ''
    agent.harbor_credential_id = int(harbor_credential_id)
    agent.harbor_type = harbor_type
    agent.harbor_url = harbor_url
    agent.harbor_user = harbor_user
    agent.harbor_ip = harbor_ip if harbor_type == 'private' else ''
    agent.keep_builds = int(data.get('keep_builds') or agent.keep_builds or 5)
    if data.get('frontend_mount_dir') is not None:
        agent.frontend_mount_dir = _norm_dir(data.get('frontend_mount_dir'))
    if data.get('nfs_server') is not None:
        agent.nfs_server = (data.get('nfs_server') or '').strip()
    if data.get('nfs_share') is not None:
        agent.nfs_share = _norm_dir(data.get('nfs_share'))
    agent.install_status = False
    db.session.commit()

    params = {
        'name': agent.name,
        'host': agent.host,
        'ssh_port': agent.ssh_port or 22,
        'ssh_username': ssh_username,
        'auth_type': auth_type,
        'ssh_password': ssh_password,
        'credential_id': credential_id,
        'master_url': master_url,
        'work_dir': agent.work_dir or '/data/cicd',
        'frontend_mount_dir': agent.frontend_mount_dir or '',
        'nfs_server': agent.nfs_server or '',
        'nfs_share': agent.nfs_share or '',
        'comm_secret': agent_service.get_comm_secret(),
        'install_docker': data.get('install_docker', True),
        'harbor_ip': agent.harbor_ip or '',
        'harbor_url': agent.harbor_url or '',
        'harbor_user': agent.harbor_user or '',
        'harbor_pass': harbor_pass_plain,
        'agent_id': agent.id,
    }

    task_id = install_service.create_install_task(params)
    return success_response({'task_id': task_id}, '安装任务已启动')


@require_permission('op:agent')
def uninstall_agent_remote(agent_id):
    """
    远程卸载 Agent（POST）：清理远程 + 删除 DB 记录
    """
    return _do_remote_cleanup(agent_id, delete_record=True)


@require_permission('op:agent')
def reset_agent_remote(agent_id):
    """
    远程重置 Agent（POST）：清理远程，保留 DB 记录，支持重新安装
    """
    return _do_remote_cleanup(agent_id, delete_record=False)


def _do_remote_cleanup(agent_id, delete_record):
    """卸载/重置公用逻辑：SSH 信息从 DB 记录读取，前端只传 remove_docker"""
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)

    data = request.json or {}

    # 从 DB 读取 SSH 连接信息
    auth_type = agent.ssh_auth_type or 'credential'
    credential_id = agent.ssh_credential_id
    if auth_type in ('credential', 'ssh_key') and not credential_id:
        return error_response('该 Agent 未保存凭据信息，无法远程操作', 400)

    params = {
        'agent_id': agent.id,
        'host': agent.host,
        'ssh_port': agent.ssh_port or 22,
        'ssh_username': agent.ssh_username or 'root',
        'auth_type': auth_type,
        'ssh_password': '',
        'credential_id': credential_id,
        'work_dir': agent.work_dir or '/data/cicd',
        'frontend_mount_dir': agent.frontend_mount_dir or '',
        'remove_nfs': data.get('remove_nfs', delete_record),  # 卸载默认 True，重置由前端勾选
        'remove_docker': data.get('remove_docker', False),
        'delete_record': delete_record,
    }

    task_id = install_service.create_uninstall_task(params)
    action = '卸载' if delete_record else '重置'
    return success_response({'task_id': task_id}, f'{action}任务已启动')


@require_permission('op:agent')
def update_agent_config(agent_id):
    """
    编辑 Agent 配置（PUT）：修改名称/主机/SSH/Harbor/前端挂载目录等。
    仅改 DB 配置，不触发重装（在线 Agent 下次心跳/任务自动感知 web_dir 变化；
    SSH/Harbor 变更在下次安装/重装时生效）。
    """
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)

    data = request.json or {}
    new_name = (data.get('name') or '').strip()
    if new_name and new_name != agent.name:
        dup = BuildAgent.query.filter(BuildAgent.name == new_name, BuildAgent.id != agent_id).first()
        if dup:
            return error_response('Agent 名称已存在', 400)
        agent.name = new_name
    if data.get('host') is not None:
        agent.host = (data.get('host') or '').strip()
    if data.get('frontend_mount_dir') is not None:
        agent.frontend_mount_dir = _norm_dir(data.get('frontend_mount_dir'))
    if data.get('nfs_server') is not None:
        agent.nfs_server = (data.get('nfs_server') or '').strip()
    if data.get('nfs_share') is not None:
        agent.nfs_share = _norm_dir(data.get('nfs_share'))
    if data.get('work_dir') is not None:
        agent.work_dir = (data.get('work_dir') or '/data/cicd').strip() or '/data/cicd'
    if data.get('keep_builds') is not None:
        agent.keep_builds = int(data.get('keep_builds') or 5)
    if data.get('disabled') is not None:
        agent.disabled = bool(data.get('disabled'))
    # SSH 连接信息（下次安装/重装生效）
    if data.get('ssh_port') is not None:
        agent.ssh_port = int(data.get('ssh_port') or 22)
    if data.get('ssh_username') is not None:
        agent.ssh_username = (data.get('ssh_username') or 'root').strip() or 'root'
    if data.get('ssh_auth_type') is not None:
        agent.ssh_auth_type = (data.get('ssh_auth_type') or 'credential').strip()
    if data.get('ssh_credential_id') is not None:
        agent.ssh_credential_id = data.get('ssh_credential_id') or None
    if data.get('master_url') is not None:
        agent.master_url = (data.get('master_url') or '').strip()
    # Harbor 信息
    if data.get('harbor_type') is not None:
        agent.harbor_type = (data.get('harbor_type') or 'public').strip()
    if data.get('harbor_url') is not None:
        agent.harbor_url = (data.get('harbor_url') or '').strip()
    if data.get('harbor_credential_id') is not None:
        agent.harbor_credential_id = data.get('harbor_credential_id') or None
    if data.get('harbor_ip') is not None:
        agent.harbor_ip = (data.get('harbor_ip') or '').strip()

    db.session.commit()
    return success_response({'id': agent.id}, 'Agent 配置已更新')


@require_permission('op:agent')
def update_agent_remote(agent_id):
    """
    远程更新 Agent（POST）：上传新版二进制 + 重启服务。
    不影响 Docker / 配置 / 工作目录，适用于仅升级 Agent 版本的场景。
    """
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)

    # 从 DB 读取 SSH 连接信息
    auth_type = agent.ssh_auth_type or 'credential'
    credential_id = agent.ssh_credential_id
    if auth_type in ('credential', 'ssh_key') and not credential_id:
        return error_response('该 Agent 未保存凭据信息，无法远程操作', 400)

    params = {
        'agent_id': agent.id,
        'host': agent.host,
        'ssh_port': agent.ssh_port or 22,
        'ssh_username': agent.ssh_username or 'root',
        'auth_type': auth_type,
        'ssh_password': '',
        'credential_id': credential_id,
    }

    task_id = install_service.create_update_task(params)
    return success_response({'task_id': task_id}, '更新任务已启动')


@require_permission('op:agent')
def toggle_agent_disable(agent_id):
    """POST /<id>/toggle-disable → 禁用/启用节点"""
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)
    agent.disabled = not agent.disabled
    db.session.commit()
    state = '已禁用' if agent.disabled else '已启用'
    return success_response({'disabled': agent.disabled}, f'{agent.name} {state}')


@require_permission('page:cicd_schedule')
def get_agent_metrics_history(agent_id):
    """
    Agent 历史指标 SSE 代理：转发到 Agent 的 /metrics 接口（SSE 流）
    GET /api/cicd/agents/<id>/metrics
    返回 SSE 流，每 3 秒推送一次历史指标数据
    """
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)
    if not agent.host:
        return error_response('Agent 无主机地址', 400)

    agent_url = f'http://{agent.host}:{agent.port or 9090}/metrics'

    def generate():
        try:
            resp = http_requests.get(agent_url, stream=True, timeout=(5, 300))
            for chunk in resp.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        except Exception as e:
            yield f'data: []\n\n'

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@require_any_permission('page:cicd', 'op:cicd_admin')
def get_docker_cache_size(agent_id):
    """
    获取 Docker 构建缓存大小（Agent 心跳上报，Redis 直读；离线返回 0B）
    GET /api/cicd/agents/<id>/docker-cache
    返回 JSON: {size: '12.3GB', raw: 13200000000}
    """
    agent = BuildAgent.query.get(agent_id)
    if not agent:
        return error_response('Agent 不存在', 404)
    try:
        from modules.cicd.services import agent_service
        hb = agent_service.get_hb(agent)
        size_str = (hb.get('docker_cache_size') if hb else '') or '0B'
        # 解析为字节数（粗略估算，仅用于展示）
        raw = 0
        size_upper = size_str.upper()
        if size_upper.endswith('GB'):
            try:
                raw = int(float(size_upper[:-2]) * 1024 * 1024 * 1024)
            except ValueError:
                pass
        elif size_upper.endswith('MB'):
            try:
                raw = int(float(size_upper[:-2]) * 1024 * 1024)
            except ValueError:
                pass
        elif size_upper.endswith('KB'):
            try:
                raw = int(float(size_upper[:-2]) * 1024)
            except ValueError:
                pass
        elif size_upper.endswith('B'):
            try:
                raw = int(size_upper[:-1])
            except ValueError:
                pass
        return success_response({'size': size_str, 'raw': raw})
    except Exception as e:
        return success_response({'size': '0B', 'raw': 0})


