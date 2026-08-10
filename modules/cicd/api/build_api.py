# -*- coding: utf-8 -*-
"""构建任务 API（触发/列表/详情/取消/步骤/日志代理/环境视图）"""
import json
import os
import time

import requests as http_requests
from flask import request, g, Response, stream_with_context

from core.response import success_response, error_response
from core.security import require_permission, require_any_permission
from modules.cicd.models import Build, BuildAgent, CicdFlowTemplate
from modules.cicd.services import build_service


@require_any_permission('page:cicd', 'op:cicd_build')
def list_builds():
    """构建列表（支持按 project/env/status 过滤）"""
    q = Build.query
    project_id = request.args.get('project_id', type=int)
    environment_id = request.args.get('environment_id', type=int)
    status = request.args.get('status', '')
    if project_id:
        q = q.filter_by(project_id=project_id)
    if environment_id:
        q = q.filter_by(environment_id=environment_id)
    if status:
        q = q.filter_by(status=status)
    builds = q.order_by(Build.created_at.desc()).limit(100).all()
    return success_response([b.to_dict() for b in builds])


@require_permission('op:cicd_build')
def trigger_build():
    """触发构建"""
    data = request.json
    project_id = data.get('project_id')
    environment_id = data.get('environment_id')
    branch = data.get('branch', '')
    services = data.get('services') or []  # 选中的服务 basename 列表，空=构建全部
    if not project_id:
        return error_response('请选择项目', 400)

    triggered_by = g.current_user.display_name() if g.current_user else 'system'
    build, err = build_service.trigger_build(project_id, environment_id, branch, triggered_by, services)
    if err:
        return error_response(err, 400)
    return success_response(build.to_dict(), '构建已提交')


@require_any_permission('page:cicd', 'op:cicd_build')
def get_build(build_id):
    """构建详情"""
    build = Build.query.get(build_id)
    if not build:
        return error_response('构建不存在', 404)
    return success_response(build.to_dict())


@require_permission('op:cicd_build')
def cancel_build(build_id):
    """取消构建"""
    ok, msg = build_service.cancel_build(build_id)
    if not ok:
        return error_response(msg, 400)
    return success_response(msg=msg)


@require_permission('op:cicd_build')
def rerun_build(build_id):
    """从指定步骤重跑构建（复用原节点构建目录，不重新 clone）"""
    data = request.json or {}
    start_step = data.get('start_step', 1)
    build, err = build_service.rerun_build(build_id, start_step)
    if err:
        return error_response(err, 400)
    return success_response(build.to_dict(), '已开始重跑')


@require_any_permission('page:cicd', 'op:cicd_build')
def stream_build(build_id):
    """构建步骤状态快照（读取 build.json），附带 DB 构建总状态"""
    build = Build.query.get(build_id)
    if not build:
        return error_response('构建不存在', 404)
    steps = build_service.get_build_steps(build.build_no)
    if steps is None:
        steps = {}
    steps['build_status'] = build.status
    return success_response(steps)


def _deploy_step_done(steps):
    """部署步骤是否已达终态；无部署步骤（前端构建）视为已完成。
    用于 SSE done 判定：构建终态 且 部署步骤终态 才真正结束。"""
    for st in (steps or {}).get('steps', []):
        if st.get('key') == 'deploy':
            return st.get('status') in ('success', 'failed', 'skipped')
    return True


@require_any_permission('page:cicd', 'op:cicd_build')
def stream_build_steps_sse(build_id):
    """
    SSE 实时推送步骤变化（监听 build.json 文件变更 + DB 状态，跨 worker 安全）
    GET /api/cicd/builds/<id>/steps/stream?token=
    首帧推送当前快照，后续仅在步骤/状态变化时推送，构建终态后自动关闭
    """
    build = Build.query.get(build_id)
    if not build:
        return error_response('构建不存在', 404)

    def generate():
        build_no = build.build_no
        json_path = os.path.join(build_service._build_dir(build_no), 'build.json')

        # 首帧：推送当前步骤快照
        steps = build_service.get_build_steps(build_no) or {}
        snapshot = {
            'build_id': build_id,
            'build_status': build.status,
            'steps': steps.get('steps', []),
        }
        if build.status in ('success', 'failed', 'cancelled') and _deploy_step_done(steps):
            snapshot['done'] = True
        yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        if snapshot.get('done'):
            return

        # 监听文件 mtime + DB 状态，有变化才推帧（服务端 1s 检测，浏览器零轮询）
        last_mtime = os.path.getmtime(json_path) if os.path.exists(json_path) else 0
        last_db_status = build.status
        heartbeat_counter = 0

        while True:
            time.sleep(1)
            changed = False

            # build.json 文件变化（Agent 回调写入）
            cur_mtime = os.path.getmtime(json_path) if os.path.exists(json_path) else 0
            if cur_mtime != last_mtime:
                last_mtime = cur_mtime
                changed = True

            # DB 状态变化（取消 / 终态落库）
            b = Build.query.get(build_id)
            if not b:
                break
            if b.status != last_db_status:
                last_db_status = b.status
                changed = True

            if changed:
                steps = build_service.get_build_steps(build_no) or {}
                evt = {
                    'build_id': build_id,
                    'build_status': b.status,
                    'steps': steps.get('steps', []),
                }
                if b.status in ('success', 'failed', 'cancelled') and _deploy_step_done(steps):
                    evt['done'] = True
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
                if evt.get('done'):
                    break
            else:
                heartbeat_counter += 1
                if heartbeat_counter >= 15:
                    heartbeat_counter = 0
                    yield ': heartbeat\n\n'  # SSE 注释行保活，浏览器自动忽略

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@require_any_permission('page:cicd', 'op:cicd_build')
def proxy_build_log(build_id):
    """
    日志代理：转发到 Agent 的日志 HTTP 接口
    GET /api/cicd/builds/<id>/log?type=all&follow=true
    type: all=总览（拼接全部步骤） / git / mvn / product / build / push
    """
    build = Build.query.get(build_id)
    if not build:
        return error_response('构建不存在', 404)

    log_type = request.args.get('type', 'all')
    follow = request.args.get('follow', 'false')
    if log_type not in ('all', 'git', 'mvn', 'product', 'build', 'push', 'deploy'):
        return error_response('无效的日志类型', 400)

    # deploy 日志由 Master 自动部署产生（不经 Agent），单独读取本地文件
    if log_type == 'deploy':
        return _stream_deploy_log(build, follow)

    # 找到执行该构建的 Agent
    agent = BuildAgent.query.get(build.agent_id) if build.agent_id else None
    if not agent or not agent.host:
        return error_response('无法定位构建 Agent', 400)

    subdir = build_service.get_build_work_subdir(build)
    agent_url = f'http://{agent.host}:{agent.port or 9090}/logs?project_env={subdir}&build_no={build.build_no}&type={log_type}&follow={follow}'

    if follow == 'true':
        # 总览日志：并行转发 Agent 流 + Master 侧部署日志（部署由 Master 后台线程执行，不经 Agent）
        if log_type == 'all':
            return _stream_all_log(build, agent_url)
        # SSE 流式代理
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
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
        )
    else:
        # 一次性返回
        try:
            resp = http_requests.get(agent_url, timeout=10)
            return Response(resp.content, content_type='text/plain; charset=utf-8')
        except Exception as e:
            return error_response(f'Agent 日志获取失败: {e}', 502)


def _stream_all_log(build, agent_url):
    """总览日志：并行转发 Agent 全流程日志（SSE 流）+ Master 侧部署日志（本地文件增量追加）。
    构建在 Agent 上执行、部署由 Master 后台线程执行，两者日志来源不同；仅透传 Agent 流
    会导致总览只见 Docker Push 结果，部署阶段日志缺失。"""
    import queue
    import threading

    deploy_path = os.path.join('logs', 'cicd', f'{build.build_no}.deploy.log')
    q = queue.Queue()

    def pump_agent():
        try:
            resp = http_requests.get(agent_url, stream=True, timeout=(5, 300))
            for chunk in resp.iter_content(chunk_size=None):
                if chunk:
                    q.put(('agent', chunk))
        except Exception as e:
            q.put(('agent_err', f'data: {{"error": "{str(e)}"}}\n\n'))
        finally:
            q.put(('agent_done', None))

    threading.Thread(target=pump_agent, daemon=True).start()

    def read_deploy():
        try:
            with open(deploy_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except OSError:
            return ''

    def sse_escape(text):
        return text.replace('\r', '').replace('\n', '\\n')

    def generate():
        sent = 0
        idle = 0
        agent_done = False
        header_sent = False
        while True:
            # 1. 排空 Agent 流队列（非阻塞；Agent 数据优先进帧，心跳帧也照常转发）
            while True:
                try:
                    kind, payload = q.get_nowait()
                except queue.Empty:
                    break
                if kind in ('agent', 'agent_err'):
                    yield payload
                    idle = 0
                elif kind == 'agent_done':
                    agent_done = True

            # 2. 每轮追加部署日志增量（构建中文件未生成时为空，不影响 Agent 转发）
            content = read_deploy()
            if content and not header_sent:
                yield 'data: ' + sse_escape('\n=== 部署 ===\n') + '\n\n'
                header_sent = True
                idle = 0
            if len(content) > sent:
                yield f'data: {sse_escape(content[sent:])}\n\n'
                sent = len(content)
                idle = 0
            else:
                idle += 1

            # 3. 结束判定：Agent 流结束且部署无新内容（部署已终态，或部署未开始且构建步骤已失败）
            steps = build_service.get_build_steps(build.build_no) or {}
            step_list = steps.get('steps', [])
            deploy_status = next((st.get('status') for st in step_list if st.get('key') == 'deploy'), None)
            deploy_done = deploy_status in ('success', 'failed', 'skipped')
            deploy_never = deploy_status in (None, 'pending')
            any_failed = any(st.get('status') == 'failed' for st in step_list)
            if agent_done and (deploy_done or (deploy_never and any_failed)):
                break
            if idle >= 300:
                break
            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


def _stream_deploy_log(build, follow):
    """Master 侧自动部署日志（logs/cicd/{build_no}.deploy.log），格式与 Agent 日志 SSE 一致"""
    log_path = os.path.join('logs', 'cicd', f'{build.build_no}.deploy.log')

    def read_all():
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except OSError:
            return ''

    def sse_escape(text):
        return text.replace('\r', '').replace('\n', '\\n')

    if follow != 'true':
        return Response(read_all(), content_type='text/plain; charset=utf-8')

    def generate():
        sent = 0
        idle = 0
        while True:
            content = read_all()
            if len(content) > sent:
                yield f'data: {sse_escape(content[sent:])}\n\n'
                sent = len(content)
                idle = 0
            else:
                idle += 1
            steps = build_service.get_build_steps(build.build_no) or {}
            deploy_status = next((st.get('status') for st in steps.get('steps', []) if st.get('key') == 'deploy'), None)
            deploy_done = deploy_status in ('success', 'failed', 'skipped')
            deploy_never = deploy_status in (None, 'pending')
            any_failed = any(st.get('status') == 'failed' for st in steps.get('steps', []))
            # 部署终态且日志无新增 → 结束；部署未开始且构建步骤已失败（不会触发部署）→ 直接结束
            if (deploy_done and len(content) <= sent) or (deploy_never and any_failed):
                break
            if idle >= 300:
                break
            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@require_permission('op:cicd_build')
def list_branches():
    """获取项目 Git 远程分支列表（用于构建弹窗下拉选择）"""
    project_id = request.args.get('project_id', type=int)
    if not project_id:
        return error_response('缺少 project_id', 400)

    template = CicdFlowTemplate.query.filter_by(project_id=project_id).first()
    if not template or not template.git_url:
        return error_response('该项目未配置 CI/CD 流程模板或 Git 地址', 400)

    from modules.cicd.services.credential_service import list_git_branches
    branches, err = list_git_branches(template.git_url, template.git_credential_id)
    if err:
        return error_response(err, 502)
    return success_response(branches)


@require_any_permission('page:cicd', 'op:cicd_build')
def list_services():
    """获取项目服务列表（模板服务目录的 basename，用于部分构建选择）"""
    project_id = request.args.get('project_id', type=int)
    if not project_id:
        return error_response('缺少 project_id', 400)

    template = CicdFlowTemplate.query.filter_by(project_id=project_id).first()
    if not template:
        return error_response('该项目未配置 CI/CD 流程模板', 400)

    # 只取服务目录的最后一级（basename），多级路径自动剔除，去重保序
    services = []
    for d in template.get_artifact_dir_list():
        base = d.strip().rstrip('/').split('/')[-1]
        if base and base not in services:
            services.append(base)
    return success_response(services)


@require_permission('page:cicd')
def env_cicd_view(environment_id):
    """
    环境关联视图：返回继承的项目模板 + last_branch + 最近执行记录
    供 cicd 面板展示（联表查询，环境管理页不改）
    """
    from modules.deploy.models import Environment
    env = Environment.query.get(environment_id)
    if not env:
        return error_response('环境不存在', 404)

    # 继承的项目模板
    template = CicdFlowTemplate.query.filter_by(project_id=env.project_id).first()
    # 上次分支记忆
    last_branch = build_service.get_env_last_branch(environment_id)
    # 最近执行记录
    builds = build_service.get_env_builds(environment_id, limit=10)

    return success_response({
        'environment_id': environment_id,
        'environment_name': env.name,
        'project_id': env.project_id,
        'project_name': env.project.name if env.project else '',
        'template': template.to_dict() if template else None,
        'last_branch': last_branch,
        'recent_builds': [b.to_dict() for b in builds],
    })
