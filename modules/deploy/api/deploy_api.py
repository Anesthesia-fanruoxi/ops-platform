# -*- coding: utf-8 -*-
"""
部署执行接口处理函数（异步模式 + SSE 进度推送）
"""
import os
import json
import time
import threading
from datetime import datetime
from flask import request, Response, current_app
from core.db import db
from modules.deploy.models import Project, Environment
from modules.system.models import Setting
from core.response import success_response, error_response
from core.security import require_permission

# 从 services 导入共享工具和任务函数
from modules.deploy.services.deploy_utils import _deploy_tasks, _tasks_lock, _get_log_path, _write_log, _clear_log
from modules.deploy.services.deploy_tasks import (
    _run_deploy_task, _run_recycle_task, _run_restore_task, _run_permanent_delete_task,
    _run_batch_recycle_task, _run_batch_restore_task, _run_batch_permanent_delete_task,
    _create_harbor_project_step
)


# ─── API 处理函数 ────────────────────────────────────────────

@require_permission('op:deploy')
def execute_deploy():
    """执行部署（异步）- 立即返回，后台线程执行"""
    data = request.json
    action = data.get('action', 'create_env')

    # 确定项目名和环境名
    if action == 'create_project':
        project_name = data.get('project_name', '').strip()
        env_name = data.get('env_name', '').strip()
    elif action == 'create_env':
        project_id = data.get('project_id')
        project = Project.query.get(project_id) if project_id else None
        project_name = project.name if project else 'unknown'
        env_name = data.get('env_name', '').strip()
    elif action == 'create_service':
        # 新增服务：通过 environment_id 反查项目/环境（前端只传 id）
        environment_id = data.get('environment_id')
        env = Environment.query.get(environment_id) if environment_id else None
        if not env or env.is_deleted:
            return error_response('环境不存在', 404)
        project = env.project
        if not project:
            return error_response('关联项目不存在', 404)
        svc_name = ''
        services = data.get('services') or []
        if services:
            raw_svc = services[0]
            svc_name = str(raw_svc.get('name', raw_svc.get('app_name', '')) if isinstance(raw_svc, dict) else raw_svc).strip()
        if not svc_name:
            return error_response('服务名称不能为空', 400)

        # NodePort 上限 32767 校验：环境已有服务数决定端口偏移，超限直接拒绝
        try:
            _env_cfg = json.loads(env.deploy_config) if env.deploy_config else {}
        except Exception:
            _env_cfg = {}
        if not isinstance(_env_cfg, dict):
            _env_cfg = {}
        _existing_count = len(_env_cfg.get('services', []))
        _base_node_port = _env_cfg.get('node_port') or ((env.port_start or 30000) + 30)
        if _base_node_port + _existing_count + 1 > 32767:
            return error_response('端口池已满（NodePort 超过 32767），无法继续新增服务', 400)

        project_name = project.name
        env_name = env.name
        # 回填供后台任务/日志使用
        data['project_id'] = project.id
        data['project_name'] = project_name
        data['env_name'] = env_name
    else:
        project_name = data.get('project_name', 'unknown')
        env_name = data.get('env_name', '').strip()

    if not env_name:
        return error_response('环境名称不能为空', 400)

    task_key = f"{project_name}-{env_name}"

    # 检查是否已有运行中的任务（锁内预置 running，防止检查与后台线程写入之间的并发空窗）
    with _tasks_lock:
        existing = _deploy_tasks.get(task_key)
        if existing and existing.get('status') == 'running':
            return error_response(f'该环境正在部署中: {task_key}', 409)
        _deploy_tasks[task_key] = {
            'status': 'running',
            'started_at': datetime.now().isoformat(),
            'project_name': project_name,
            'env_name': env_name,
        }

    # 清空旧日志，写入启动标记
    action_type_map = {'create_project': 'project', 'create_env': 'environment', 'create_service': 'service'}
    log_file = _get_log_path(project_name, env_name, action_type_map.get(action, 'environment'))
    _clear_log(log_file)
    _write_log(log_file, 'INFO', f'===== 开始部署: {project_name}-{env_name} ({action}) =====')

    # 启动后台线程
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_deploy_task, args=(app, task_key, data), daemon=True)
    t.start()

    return success_response({
        'project': project_name,
        'env': env_name,
        'status': 'running',
        'log_file': log_file
    }, '部署任务已提交')


def deploy_stream():
    """部署进度流 - 读取日志文件实时推送（已登录即可访问，操作权限由各触发接口单独校验）"""
    project_name = request.args.get('project', '')
    env_name = request.args.get('env', '')
    action = request.args.get('action', 'environment')

    # sync 操作不需要 project/env 参数
    if action == 'sync':
        log_file = os.path.join('logs', 'sync.log')
        task_key = 'sync'
    elif action == 'nginx-sync':
        log_file = os.path.join('logs', 'nginx-sync.log')
        task_key = 'nginx-sync'
    elif action.startswith('batch-'):
        # 批量操作通过 task_key 参数定位日志
        task_key = request.args.get('task_key', '')
        if not task_key:
            return error_response('缺少 task_key 参数', 400)
        with _tasks_lock:
            task = _deploy_tasks.get(task_key)
        log_file = task['log_file'] if task and task.get('log_file') else None
        if not log_file:
            return error_response('任务不存在或日志文件未找到', 404)
    else:
        if not project_name or not env_name:
            return error_response('缺少 project 或 env 参数', 400)
        # 与 execute_deploy 保持一致的 action 映射
        action_type_map = {'create_project': 'project', 'create_env': 'environment', 'create_service': 'service'}
        mapped_action = action_type_map.get(action, action)
        log_file = _get_log_path(project_name, env_name, mapped_action)
        action_suffix_map = {'environment': '', 'recycle': '-recycle', 'restore': '-restore',
                             'permanent-delete': '-permanent-delete',
                             'project': '', 'service': ''}
        suffix = action_suffix_map.get(mapped_action, '')
        task_key = f"{project_name}-{env_name}{suffix}"

    def generate():
        if not os.path.exists(log_file):
            # 等待日志文件创建
            for _ in range(30):
                if os.path.exists(log_file):
                    break
                time.sleep(0.5)
            else:
                yield f"data: {json.dumps({'done': True, 'success': False, 'message': '日志文件未创建'})}\n\n"
                return

        with open(log_file, 'r', encoding='utf-8') as f:
            # 先发送已有内容
            for line in f:
                line = line.strip()
                if line:
                    parsed = _parse_log_line(line)
                    if parsed:
                        yield f"data: {json.dumps(parsed, ensure_ascii=False)}\n\n"
                    if '[DONE]' in line or '[FAILED]' in line:
                        done_data = {'done': True, 'success': '[DONE]' in line, 'message': line}
                        yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
                        return

            # tail -f: 持续监听新内容
            while True:
                line = f.readline()
                if line:
                    line = line.strip()
                    if line:
                        parsed = _parse_log_line(line)
                        if parsed:
                            yield f"data: {json.dumps(parsed, ensure_ascii=False)}\n\n"
                        if '[DONE]' in line or '[FAILED]' in line:
                            done_data = {'done': True, 'success': '[DONE]' in line, 'message': line}
                            yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
                            return
                else:
                    # 检查任务是否已结束
                    with _tasks_lock:
                        task = _deploy_tasks.get(task_key)
                    if task and task.get('status') in ('completed', 'failed'):
                        done_data = {'done': True, 'success': task['status'] == 'completed',
                                     'message': f"任务{task['status']}"}
                        yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
                        return
                    time.sleep(0.5)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@require_permission('page:create')
def deploy_status():
    """查询部署任务状态"""
    project_name = request.args.get('project', '')
    env_name = request.args.get('env', '')

    if not project_name or not env_name:
        return error_response('缺少 project 或 env 参数', 400)

    task_key = f"{project_name}-{env_name}"
    with _tasks_lock:
        task = _deploy_tasks.get(task_key)

    if not task:
        return success_response({'status': 'idle', 'project': project_name, 'env': env_name})

    return success_response({
        'project': project_name,
        'env': env_name,
        'status': task.get('status'),
        'started_at': task.get('started_at'),
        'log_file': task.get('log_file')
    })


@require_permission('op:recycle')
def recycle_async():
    """异步回收环境"""
    from datetime import datetime as dt
    data = request.json
    env_id = data.get('environment_id')
    if not env_id:
        return error_response('缺少 environment_id', 400)

    env = Environment.query.get(env_id)
    if not env:
        return error_response('环境不存在', 404)
    project = env.project
    if not project:
        return error_response('关联项目不存在', 404)

    project_name = project.name
    env_name = env.name
    task_key = f"{project_name}-{env_name}-recycle"

    with _tasks_lock:
        existing = _deploy_tasks.get(task_key)
        if existing and existing.get('status') == 'running':
            return error_response(f'该环境正在回收中', 409)

    log_file = _get_log_path(project_name, env_name, 'recycle')
    _clear_log(log_file)
    _write_log(log_file, 'INFO', f'===== 开始回收: {project_name}-{env_name} =====')

    app = current_app._get_current_object()
    t = threading.Thread(target=_run_recycle_task, args=(app, task_key, env_id), daemon=True)
    t.start()

    return success_response({
        'project': project_name, 'env': env_name,
        'status': 'running', 'action': 'recycle'
    }, '回收任务已提交')


@require_permission('op:recycle_admin')
def restore_async():
    """异步恢复环境"""
    from datetime import datetime as dt
    data = request.json
    env_id = data.get('environment_id')
    if not env_id:
        return error_response('缺少 environment_id', 400)

    env = Environment.query.get(env_id)
    if not env:
        return error_response('环境不存在', 404)
    if not env.is_deleted:
        return error_response('环境未被删除，无法恢复', 400)
    project = env.project
    if not project:
        return error_response('关联项目不存在', 404)

    project_name = project.name
    env_name = env.name
    task_key = f"{project_name}-{env_name}-restore"

    with _tasks_lock:
        existing = _deploy_tasks.get(task_key)
        if existing and existing.get('status') == 'running':
            return error_response(f'该环境正在恢复中', 409)

    log_file = _get_log_path(project_name, env_name, 'restore')
    _clear_log(log_file)
    _write_log(log_file, 'INFO', f'===== 开始恢复: {project_name}-{env_name} =====')

    app = current_app._get_current_object()
    t = threading.Thread(target=_run_restore_task, args=(app, task_key, env_id), daemon=True)
    t.start()

    return success_response({
        'project': project_name, 'env': env_name,
        'status': 'running', 'action': 'restore'
    }, '恢复任务已提交')


@require_permission('op:recycle_admin')
def permanent_delete_async():
    """异步彻底删除环境（SSE进度推送）"""
    data = request.json
    env_id = data.get('environment_id')
    if not env_id:
        return error_response('缺少 environment_id', 400)

    env = Environment.query.get(env_id)
    if not env:
        return error_response('环境不存在', 404)
    if not env.is_deleted:
        return error_response('只能彻底删除已回收的环境', 400)
    project = env.project
    if not project:
        return error_response('关联项目不存在', 404)

    project_name = project.name
    env_name = env.name
    task_key = f"{project_name}-{env_name}-permanent-delete"

    with _tasks_lock:
        existing = _deploy_tasks.get(task_key)
        if existing and existing.get('status') == 'running':
            return error_response(f'该环境正在彻底删除中', 409)

    log_file = _get_log_path(project_name, env_name, 'permanent-delete')
    _clear_log(log_file)
    _write_log(log_file, 'INFO', f'===== 开始彻底删除: {project_name}-{env_name} =====')

    app = current_app._get_current_object()
    t = threading.Thread(target=_run_permanent_delete_task, args=(app, task_key, env_id), daemon=True)
    t.start()

    return success_response({
        'project': project_name, 'env': env_name,
        'status': 'running', 'action': 'permanent-delete'
    }, '彻底删除任务已提交')


@require_permission('op:recycle_admin')
def batch_permanent_delete_async():
    """异步批量彻底删除环境（SSE进度推送，串行执行）"""
    data = request.json
    env_ids = data.get('environment_ids', [])
    if not env_ids:
        return error_response('缺少 environment_ids', 400)

    # 验证所有环境存在且已回收
    valid_ids = []
    names = []
    for eid in env_ids:
        env = Environment.query.get(eid)
        if not env:
            continue
        if not env.is_deleted:
            continue
        project = env.project
        if not project:
            continue
        valid_ids.append(eid)
        names.append(f'{project.name}-{env.name}')

    if not valid_ids:
        return error_response('没有可删除的环境', 400)

    task_key = f'batch-permanent-delete-{int(time.time())}'

    batch_log_dir = os.path.join('logs', 'batch')
    os.makedirs(batch_log_dir, exist_ok=True)
    from datetime import datetime
    batch_log = os.path.join(batch_log_dir, f'batch-permanent-delete-{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    _write_log(batch_log, 'INFO', f'===== 批量彻底删除任务已提交: {len(valid_ids)}个环境 =====')

    app = current_app._get_current_object()
    t = threading.Thread(target=_run_batch_permanent_delete_task, args=(app, task_key, valid_ids), daemon=True)
    t.start()

    return success_response({
        'task_key': task_key,
        'count': len(valid_ids),
        'names': names,
        'status': 'running',
        'action': 'batch-permanent-delete'
    }, '批量彻底删除任务已提交')


def _create_batch_task(env_ids, action, task_func, require_deleted=None):
    """通用批量任务创建器"""
    valid_ids = []
    names = []
    for eid in env_ids:
        env = Environment.query.get(eid)
        if not env or not env.project:
            continue
        if require_deleted is not None and env.is_deleted != require_deleted:
            continue
        valid_ids.append(eid)
        names.append(f'{env.project.name}-{env.name}')

    if not valid_ids:
        return error_response('没有可操作的环境', 400)

    task_key = f'batch-{action}-{int(time.time())}'
    batch_log_dir = os.path.join('logs', 'batch')
    os.makedirs(batch_log_dir, exist_ok=True)
    from datetime import datetime
    batch_log = os.path.join(batch_log_dir, f'batch-{action}-{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    _write_log(batch_log, 'INFO', f'===== 批量{action}任务已提交: {len(valid_ids)}个环境 =====')

    app = current_app._get_current_object()
    t = threading.Thread(target=task_func, args=(app, task_key, valid_ids), daemon=True)
    t.start()

    return success_response({
        'task_key': task_key,
        'count': len(valid_ids),
        'names': names,
        'status': 'running',
        'action': f'batch-{action}'
    }, f'批量{action}任务已提交')


@require_permission('op:recycle')
def batch_recycle_async():
    """异步批量回收"""
    data = request.json
    env_ids = data.get('environment_ids', [])
    if not env_ids:
        return error_response('缺少 environment_ids', 400)
    return _create_batch_task(env_ids, 'recycle', _run_batch_recycle_task, require_deleted=False)


@require_permission('op:recycle_admin')
def batch_restore_async():
    """异步批量恢复"""
    data = request.json
    env_ids = data.get('environment_ids', [])
    if not env_ids:
        return error_response('缺少 environment_ids', 400)
    return _create_batch_task(env_ids, 'restore', _run_batch_restore_task, require_deleted=True)


def _parse_log_line(line):
    """解析日志行为 SSE 数据"""
    # 格式: [2026-07-09 15:30:01] [INFO] [步骤1/5] 保存配置到数据库...
    # 或:   [2026-07-09 15:30:01] [OK] 配置保存成功
    try:
        if not line.startswith('['):
            return {'message': line}
        # 提取时间
        ts_end = line.index(']', 1)
        ts = line[1:ts_end]
        # 提取级别
        rest = line[ts_end + 2:]
        lvl_end = rest.index(']', 1)
        level = rest[1:lvl_end]
        # 剩余内容
        message = rest[lvl_end + 2:].strip()
        # 提取步骤
        step = None
        if message.startswith('[步骤') or message.startswith('[步骤'):
            step_end = message.index(']')
            step = message[1:step_end]
            message = message[step_end + 2:].strip()

        return {'time': ts, 'level': level, 'step': step, 'message': message}
    except Exception:
        return {'message': line}

