# -*- coding: utf-8 -*-
"""
构建服务：触发构建（快照）、取消、结果落库、步骤状态管理
"""
import os
import re
import json
import shutil
from datetime import datetime

from core.db import db
from modules.cicd.models import Build, CicdFlowTemplate, BuildAgent
from modules.cicd.services.dockerfile_service import render_for_build
from modules.cicd.services import agent_service

# 构建日志目录
BUILD_LOG_DIR = os.path.join('logs', 'cicd')


def get_build_work_subdir(build):
    """计算 Agent 构建工作子目录名：{project}-{env}（文件系统安全，任务推送与日志查询两端一致）"""
    proj = build.project.name if build.project else 'unknown'
    env = build.environment.name if build.environment else 'default'
    return re.sub(r'[^A-Za-z0-9_-]', '-', f'{proj}-{env}')

# 动态步骤定义：根据 project_type 生成
BACKEND_STEPS = [
    {'step_no': 1, 'key': 'clone', 'name': 'Git Clone'},
    {'step_no': 2, 'key': 'build', 'name': '编译构建'},
    {'step_no': 3, 'key': 'collect', 'name': '产物收集'},
    {'step_no': 4, 'key': 'docker_build', 'name': 'Docker Build'},
    {'step_no': 5, 'key': 'docker_push', 'name': 'Docker Push'},
    {'step_no': 6, 'key': 'deploy', 'name': '部署'},
]

FRONTEND_STEPS = [
    {'step_no': 1, 'key': 'clone', 'name': 'Git Clone'},
    {'step_no': 2, 'key': 'build', 'name': '编译构建'},
    {'step_no': 3, 'key': 'collect', 'name': '产物收集'},
]


def get_build_steps_def(project_type):
    """根据项目类型获取步骤定义"""
    if project_type == 'frontend':
        return FRONTEND_STEPS
    return BACKEND_STEPS


def _generate_build_no():
    """生成构建编号：B + 时间戳 + 4位随机"""
    import random
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    return f'B{ts}{random.randint(1000, 9999)}'


def trigger_build(project_id, environment_id, branch, triggered_by, services=None):
    """
    触发构建：从项目大模板快照配置，创建 pending Build 记录。
    services: 选中的服务 basename 列表，空/None = 构建全部服务。
    返回 (build, error_msg)
    """
    # 查项目大模板
    template = CicdFlowTemplate.query.filter_by(project_id=project_id).first()
    if not template:
        return None, '该项目未配置 CI/CD 流程模板'

    # 确保日志目录存在
    os.makedirs(BUILD_LOG_DIR, exist_ok=True)

    build_no = _generate_build_no()
    log_file = os.path.join(BUILD_LOG_DIR, f'{build_no}.log')

    # 渲染 Dockerfile 快照（后端才需要）
    dockerfile_content = ''
    if template.project_type == 'backend' and template.dockerfile_template_id:
        dockerfile_content = render_for_build(template.dockerfile_template_id, {
            'image_name': template.image_name or '',
            'project_type': template.language or '',
            'project_name': template.project.name if template.project else '',
        })

    # 生成 image_tag（分支名 + 短时间戳）
    safe_branch = (branch or 'master').replace('/', '-').replace('\\', '-')
    image_tag = f'{safe_branch}-{datetime.now().strftime("%Y%m%d%H%M%S")}'

    # 组装完整步骤配置快照
    steps_config = {
        'git_docker_image': template.git_docker_image or '',
        'git_url': template.git_url or '',
        'git_credential_id': template.git_credential_id,
        'build_docker_image': template.build_docker_image or '',
        'build_command': template.build_command or '',
        'artifact_dirs': template.get_artifact_dir_list(),
        'artifact_dir': template.artifact_dir or '',
        'services': services or [],  # 选中的服务 basename，空=构建全部
        'dockerfile_content': dockerfile_content,
        'image_name': template.image_name or '',
        'image_tag': image_tag,
    }

    build = Build(
        build_no=build_no,
        project_id=project_id,
        environment_id=environment_id,
        branch=branch or 'master',
        project_type=template.project_type,
        language=template.language or '',
        steps_snapshot=json.dumps(steps_config, ensure_ascii=False),
        image_name=template.image_name,
        image_tag=image_tag,
        status='pending',
        log_file=log_file,
        triggered_by=triggered_by,
    )
    db.session.add(build)
    db.session.commit()

    # 初始化步骤状态文件
    init_build_steps(build_no, template.project_type)

    # 触发调度：立即尝试派发给最优空闲 Agent
    from modules.cicd.services.dispatch_service import dispatch_pending
    dispatch_pending()

    return build, None


def cancel_build(build_id):
    """取消构建：仅 pending 可直接取消；running 标记取消意图"""
    build = Build.query.get(build_id)
    if not build:
        return False, '构建不存在'
    if build.status == 'pending':
        build.status = 'cancelled'
        build.finished_at = datetime.now()
        db.session.commit()
        from core.redis_client import cache_delete
        cache_delete(f'build:claim:{build.id}')
        return True, '已取消'
    if build.status == 'running':
        build.cancel_requested = True
        db.session.commit()
        # 主动推送 kill 信号到执行节点，即时终止当前运行的容器/进程（失败则由步骤边界检查兜底）
        if build.agent_id:
            agent = BuildAgent.query.get(build.agent_id)
            if agent:
                from modules.cicd.services.dispatch_service import push_cancel_to_agent
                push_cancel_to_agent(agent, build)
        return True, '已发送取消请求（等待 Agent 响应）'
    return False, f'当前状态 {build.status} 不可取消'


def rerun_build(build_id, start_step):
    """
    从指定步骤重跑构建（原地复用同一条记录、同一构建目录，不重新 clone）。
    除 running 外任何状态（含 success）均可重跑；必须派发回原构建节点（目录在其磁盘上）。
    start_step 之前的步骤必须均为 success（复用其产物）。
    重跑进入调度队列（状态置 pending、保留 agent_id 钉住原节点），节点繁忙则排队等待。
    返回 (build, error_msg)
    """
    build = Build.query.get(build_id)
    if not build:
        return None, '构建不存在'
    if build.status == 'running':
        return None, '构建正在运行中，请等待完成或取消后再重跑'
    if not build.agent_id:
        return None, '该构建未在节点上执行过，无法重跑，请重新触发构建'

    # 校验并重置 build.json 步骤状态
    data = get_build_steps(build.build_no)
    if not data or not data.get('steps'):
        return None, '步骤状态文件不存在，无法重跑'
    steps = data['steps']
    total = len(steps)
    try:
        start_step = int(start_step)
    except (TypeError, ValueError):
        return None, 'start_step 无效'
    if not (1 <= start_step <= total):
        return None, f'start_step 必须在 1~{total} 之间'
    for s in steps:
        if s['step_no'] < start_step and s['status'] != 'success':
            return None, f'前置步骤「{s["name"]}」未完成（{s["status"]}），请从更早步骤重跑'
    for s in steps:
        if s['step_no'] >= start_step:
            s['status'] = 'pending'
            s['started_at'] = None
            s['finished_at'] = None
            s['duration'] = None
            s['error'] = ''
    data['status'] = 'pending'
    _write_build_json(_build_dir(build.build_no), data)

    # 记录重跑起点，供 assemble_task 下发给 Agent
    snapshot = build.get_steps_snapshot()
    snapshot['start_step'] = start_step
    build.steps_snapshot = json.dumps(snapshot, ensure_ascii=False)

    # 进入调度队列：保留 agent_id 钉住原节点，状态置 pending 等待调度派发
    build.status = 'pending'
    build.cancel_requested = False
    build.started_at = None
    build.finished_at = None
    build.duration = None
    build.error_msg = ''
    build.image_digest = ''
    db.session.commit()

    # 清除可能残留的领取标记，保证重跑可被正常领取
    from core.redis_client import cache_delete
    cache_delete(f'build:claim:{build.id}')

    # 触发调度：重跑任务优先派发；节点繁忙/不可用则保持 pending 排队等待
    from modules.cicd.services.dispatch_service import dispatch_pending
    dispatch_pending()

    return build, '已加入重跑队列'


def complete_build(build_id, status, image_digest='', error=''):
    """
    Agent 回调：构建完成，落库终态。
    status: success | failed
    """
    build = Build.query.get(build_id)
    if not build:
        return None

    build.status = status
    build.image_digest = image_digest or ''
    build.error_msg = error or ''
    build.finished_at = datetime.now()
    if build.started_at:
        build.duration = (build.finished_at - build.started_at).total_seconds()

    # 释放 agent 负载
    if build.agent_id:
        agent_service.release_agent_load(build.agent_id)

    db.session.commit()

    # 清除领取标记（终态由 status 兜底）
    from core.redis_client import cache_delete
    cache_delete(f'build:claim:{build.id}')

    # 释放容量后触发调度，消化排队任务
    from modules.cicd.services.dispatch_service import dispatch_pending
    dispatch_pending()

    # 同步清理超额构建记录（保留数跟随执行节点配置，默认 5）
    keep = 5
    if build.agent_id:
        agent = BuildAgent.query.get(build.agent_id)
        if agent and agent.keep_builds:
            keep = agent.keep_builds
    cleanup_old_build_records(build.environment_id, keep)

    return build


def cleanup_old_build_records(environment_id, keep):
    """与 Agent 目录保留策略同步：每个环境仅保留最近 keep 条构建记录。
    超出且为终态的记录，同步删除其步骤状态目录、日志文件、关联调度日志与 DB 记录。"""
    if not environment_id:
        return
    try:
        keep = int(keep)
    except (TypeError, ValueError):
        keep = 5
    if keep < 1:
        keep = 1
    builds = Build.query.filter_by(environment_id=environment_id).order_by(Build.created_at.desc()).all()
    if len(builds) <= keep:
        return
    removed = 0
    for old in builds[keep:]:
        if old.status in ('pending', 'running'):
            continue  # 保险：不清理未结束的构建
        shutil.rmtree(_build_dir(old.build_no), ignore_errors=True)
        try:
            if old.log_file and os.path.exists(old.log_file):
                os.remove(old.log_file)
        except OSError:
            pass
        # 调度日志独立保留（最近 100 条），不随构建记录同步删除
        db.session.delete(old)
        removed += 1
    if removed:
        db.session.commit()


def get_env_last_branch(environment_id):
    """获取环境最近一次构建的分支（独立记忆）"""
    last_build = Build.query.filter_by(
        environment_id=environment_id
    ).order_by(Build.created_at.desc()).first()
    return last_build.branch if last_build else ''


def get_env_builds(environment_id, limit=20):
    """获取环境的执行记录"""
    return Build.query.filter_by(
        environment_id=environment_id
    ).order_by(Build.created_at.desc()).limit(limit).all()


# ─── 步骤状态文件管理 ─────────────────────────────────────

def _build_dir(build_no):
    """获取构建目录"""
    return os.path.join(BUILD_LOG_DIR, build_no)


def init_build_steps(build_no, project_type='backend'):
    """初始化 build.json，所有步骤状态为 pending"""
    bdir = _build_dir(build_no)
    os.makedirs(bdir, exist_ok=True)
    steps_def = get_build_steps_def(project_type)
    steps = []
    for s in steps_def:
        steps.append({
            'step_no': s['step_no'],
            'key': s['key'],
            'name': s['name'],
            'status': 'pending',
            'started_at': None,
            'finished_at': None,
            'duration': None,
            'error': '',
        })
    data = {'build_no': build_no, 'status': 'pending', 'project_type': project_type, 'steps': steps}
    _write_build_json(bdir, data)
    return data


def _parse_step_time(s):
    """解析步骤时间字符串，兼容秒级和毫秒级两种格式

    Returns:
        datetime or None
    """
    if not s:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def update_step_status(build_no, step_no, status, error=''):
    """更新指定步骤状态，并同步 build 总状态"""
    bdir = _build_dir(build_no)
    data = _read_build_json(bdir)
    if not data:
        data = init_build_steps(build_no)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    for step in data['steps']:
        if step['step_no'] == step_no:
            if status == 'running':
                step['status'] = 'running'
                step['started_at'] = now_str
            elif status in ('success', 'failed'):
                step['status'] = status
                step['finished_at'] = now_str
                step['error'] = error or ''
                # 计算耗时
                st = _parse_step_time(step.get('started_at'))
                if st:
                    step['duration'] = round((datetime.now() - st).total_seconds(), 1)
                # 失败时后续步骤标记为 skipped
                if status == 'failed':
                    for s2 in data['steps']:
                        if s2['step_no'] > step_no and s2['status'] == 'pending':
                            s2['status'] = 'skipped'
            break

    # 计算 build 总状态
    statuses = [s['status'] for s in data['steps']]
    if any(s == 'failed' for s in statuses):
        data['status'] = 'failed'
    elif all(s == 'success' for s in statuses):
        data['status'] = 'success'
    elif any(s == 'running' for s in statuses):
        data['status'] = 'running'
    else:
        data['status'] = 'pending'

    _write_build_json(bdir, data)
    return data


def get_build_steps(build_no):
    """读取 build.json 步骤状态"""
    bdir = _build_dir(build_no)
    return _read_build_json(bdir)


def update_deploy_step(build_no, status, error=''):
    """更新 build.json 中「部署」步骤（key='deploy'）的状态。
    由 Master 自动部署调用（Agent 不感知此步）；不重算 build 总状态，
    展示以 DB build.status 为准（部署失败不影响构建终态）。"""
    bdir = _build_dir(build_no)
    data = _read_build_json(bdir)
    if not data or not data.get('steps'):
        return
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    for step in data['steps']:
        if step.get('key') != 'deploy':
            continue
        if status == 'running':
            step['status'] = 'running'
            step['started_at'] = now_str
            step['error'] = ''
        elif status in ('success', 'failed', 'skipped'):
            step['status'] = status
            step['finished_at'] = now_str
            step['error'] = error or ''
            st = _parse_step_time(step.get('started_at'))
            if st:
                step['duration'] = round((datetime.now() - st).total_seconds(), 1)
        break
    _write_build_json(bdir, data)


def _write_build_json(bdir, data):
    path = os.path.join(bdir, 'build.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_build_json(bdir):
    path = os.path.join(bdir, 'build.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
