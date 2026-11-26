# -*- coding: utf-8 -*-
"""多仓库模板：配置保存 + 构建触发（独立于单仓流程模板）

构建逻辑通过 build_service.trigger_build(multi_item_id=...) 进入本模块，
单仓路径完全不经过这里。
"""
import json
import os
import random
import re
from datetime import datetime

from core.db import db
from modules.cicd.models import Build
from modules.cicd.multi_models import (
    CicdMultiTemplate, CicdMultiItem, CicdMultiService, CicdBuildBatch,
)
from modules.cicd.services.dockerfile_service import render_for_build

_REPO_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
# 服务名同时是镜像名与 K8s 名称：小写字母/数字/-
_SERVICE_NAME = re.compile(r'^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$')


def _derive_repo_name(url):
    """仓库名取 Git 地址最后一段并去掉 .git（表单不再要求手填仓库名）"""
    s = (url or '').strip().rstrip('/')
    if not s:
        return ''
    name = re.split(r'[/:]', s)[-1]
    if name.lower().endswith('.git'):
        name = name[:-4]
    return name


def _dns_label(value):
    """服务名兜底：转成小写 DNS label，保证镜像名/K8s 名合法"""
    s = re.sub(r'[^a-z0-9-]+', '-', (value or '').lower()).strip('-')
    return s or 'app'


def get_by_project(project_id):
    return CicdMultiTemplate.query.filter_by(project_id=project_id).first()


def get_template(tpl_id):
    return CicdMultiTemplate.query.get(tpl_id)


def item_services(item_id):
    return CicdMultiService.query.filter_by(item_id=item_id, enabled=True) \
        .order_by(CicdMultiService.sort_no.asc(), CicdMultiService.id.asc()).all()


def _clean_rel_path(value, allow_empty=True):
    """相对路径校验：禁止绝对路径与 .. 逃逸"""
    p = (value or '').strip().replace('\\', '/')
    if not p:
        return '' if allow_empty else None
    if p.startswith('/') or p == '..' or p.startswith('../') or '/../' in p:
        return None
    return p.rstrip('/') or '.'


def _service_map(item, services):
    """服务映射：服务目录相对「构建目录」，Agent 侧相对仓库根"""
    if not services:
        # 兜底：整仓一个镜像，用仓库名当服务名，保证至少能出镜像
        return [{'name': _dns_label(item.repo_name), 'dir': '.', 'jar_name': ''}]
    return [{
        'name': s.service_name,
        'dir': s.artifact_dir or '.',
        'jar_name': s.jar_name or '',
    } for s in services]


def save_template(data, tpl_id=None):
    """创建/更新多仓库模板（含仓库行与服务映射），返回 (template, error)"""
    project_id = data.get('project_id')
    if not project_id:
        return None, '请选择项目'
    from modules.deploy.models import Project
    project = Project.query.get(project_id)
    if not project:
        return None, '项目不存在'

    tpl = CicdMultiTemplate.query.get(tpl_id) if tpl_id else None
    if tpl_id and not tpl:
        return None, '模板不存在'
    if not tpl:
        # 新建前先查重（不能先 add 再查：autoflush 会把新行查出来当成重复）
        dup = CicdMultiTemplate.query.filter_by(project_id=project_id).first()
        if dup:
            return None, f'项目「{project.name}」已有多仓库模板，请直接编辑'
        tpl = CicdMultiTemplate(project_id=project_id)
        db.session.add(tpl)
    else:
        tpl.project_id = project_id
        dup = CicdMultiTemplate.query.filter(
            CicdMultiTemplate.project_id == project_id,
            CicdMultiTemplate.id != tpl.id
        ).first()
        if dup:
            return None, f'项目「{project.name}」已有多仓库模板，请直接编辑'

    tpl.name = (data.get('name') or f'{project.name} 多仓库模板').strip()[:100]
    tpl.description = (data.get('description') or '').strip()[:300]
    if 'publish_artifacts' in data:
        tpl.publish_artifacts = bool(data.get('publish_artifacts'))
    if 'maven_settings_id' in data:
        from modules.cicd.models import MavenSettings
        settings_id = data.get('maven_settings_id') or None
        if settings_id and not MavenSettings.query.get(settings_id):
            return None, 'Maven Settings 不存在'
        tpl.maven_settings_id = settings_id
    db.session.flush()

    items = data.get('items') or []
    if not isinstance(items, list) or not items:
        return None, '请至少配置一个仓库'

    seen_repo = set()
    keep_ids = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            return None, f'第 {idx + 1} 行仓库格式不正确'
        git_url = (raw.get('git_url') or '').strip()
        if not git_url:
            return None, f'第 {idx + 1} 行未填 Git 地址'
        repo_name = _derive_repo_name(git_url)
        if not _REPO_NAME.match(repo_name):
            return None, f'第 {idx + 1} 行无法从 Git 地址识别合法仓库名：{repo_name or "(空)"}'
        if repo_name in seen_repo:
            return None, f'仓库名重复（Git 地址最后一段相同）：{repo_name}'
        seen_repo.add(repo_name)

        build_command = (raw.get('build_command') or '').strip()
        if not build_command:
            return None, f'仓库「{repo_name}」未填编译命令'

        item = None
        if raw.get('id'):
            item = CicdMultiItem.query.filter_by(id=raw['id'], template_id=tpl.id).first()
        if not item:
            item = CicdMultiItem.query.filter_by(template_id=tpl.id, repo_name=repo_name).first()
        if not item:
            item = CicdMultiItem(template_id=tpl.id, repo_name=repo_name)
            db.session.add(item)

        item.repo_name = repo_name
        item.git_url = git_url
        item.git_credential_id = raw.get('git_credential_id') or None
        if 'language' in raw:
            item.language = (raw.get('language') or '').strip()[:30]
        item.git_docker_image = (raw.get('git_docker_image') or 'hub.hzbxhd.com/library/git-clone:1.0').strip()[:200]
        item.build_docker_image = (raw.get('build_docker_image') or '').strip()[:200]
        item.build_command = build_command
        item.dockerfile_template_id = raw.get('dockerfile_template_id') or None
        item.description = (raw.get('description') or '').strip()[:200]
        item.enabled = bool(raw.get('enabled', True))
        item.sort_no = idx
        db.session.flush()
        keep_ids.append(item.id)

        # 服务映射整体替换（构建快照会保存当时的映射，历史构建不受影响）
        CicdMultiService.query.filter_by(item_id=item.id).delete(synchronize_session=False)
        seen_svc = set()
        for s_idx, s in enumerate(raw.get('services') or []):
            if not isinstance(s, dict):
                continue
            sname = (s.get('service_name') or s.get('name') or '').strip()
            if not sname:
                continue
            if not _SERVICE_NAME.match(sname):
                return None, f'仓库「{repo_name}」服务名不合法（小写字母/数字/-）：{sname}'
            if sname in seen_svc:
                return None, f'仓库「{repo_name}」服务名重复：{sname}'
            seen_svc.add(sname)
            sdir = _clean_rel_path(s.get('artifact_dir') or '.')
            if sdir is None:
                return None, f'服务「{sname}」产物目录不合法'
            db.session.add(CicdMultiService(
                item_id=item.id,
                service_name=sname,
                artifact_dir=sdir or '.',
                jar_name=(s.get('jar_name') or '').strip()[:200],
                jvm=(s.get('jvm') or '').strip()[:10],
                sort_no=s_idx,
                enabled=True,
            ))

    # 删除本次未提交的仓库行及其服务
    for old in CicdMultiItem.query.filter_by(template_id=tpl.id).all():
        if old.id not in keep_ids:
            CicdMultiService.query.filter_by(item_id=old.id).delete(synchronize_session=False)
            db.session.delete(old)

    db.session.commit()
    return tpl, None


def delete_template(tpl_id):
    tpl = CicdMultiTemplate.query.get(tpl_id)
    if not tpl:
        return False, '模板不存在'
    for item in CicdMultiItem.query.filter_by(template_id=tpl.id).all():
        CicdMultiService.query.filter_by(item_id=item.id).delete(synchronize_session=False)
        db.session.delete(item)
    db.session.delete(tpl)
    db.session.commit()
    return True, ''


def list_item_branches(item_id):
    item = CicdMultiItem.query.get(item_id)
    if not item:
        return None, '仓库不存在'
    if not item.git_url:
        return None, '该仓库未配置 Git 地址'
    from modules.cicd.services.credential_service import list_git_branches
    return list_git_branches(item.git_url, item.git_credential_id)


def trigger_item_build(item_id, environment_id, branch, triggered_by, maven_settings_id=None, dispatch=True, service_names=None, batch_id=None):
    """多仓库构建入口：单仓流程模板不经过这里。返回 (build, error)"""
    item = CicdMultiItem.query.get(item_id)
    if not item:
        return None, '仓库不存在'
    if not item.enabled:
        return None, f'仓库「{item.repo_name}」已禁用'
    tpl = CicdMultiTemplate.query.get(item.template_id)
    if not tpl:
        return None, '多仓库模板不存在'

    from modules.deploy.models import Environment
    env = Environment.query.get(environment_id) if environment_id else None
    if not env or env.is_deleted:
        return None, '环境不存在'
    if int(env.project_id) != int(tpl.project_id):
        return None, '环境与模板不属于同一项目'

    settings_id = maven_settings_id or tpl.maven_settings_id
    settings = None
    if settings_id:
        from modules.cicd.models import MavenSettings
        settings = MavenSettings.query.get(settings_id)
        if not settings:
            return None, 'Maven Settings 不存在'

    branch = (branch or 'master').strip()
    services = item_services(item.id)
    if service_names:
        wanted = set(service_names)
        services = [s for s in services if s.service_name in wanted]
        if not services:
            return None, '选中的服务不在该仓库的服务映射中'
    srv_map = _service_map(item, services)

    build_command = item.build_command.strip()
    if tpl.publish_artifacts:
        if not settings:
            return None, '已开启制品发布，请先选择 Maven Settings'
        if not settings.release_url or not settings.snapshot_url:
            return None, '所选 Maven Settings 未配置 release / snapshot 发布地址'
        # 制品发布：package 与 deploy:deploy 必须在同一次 Maven 会话里执行，
        # 否则 jar 模块没有产物文件，报 "The packaging for this project did not assign a file
        # to the build artifact"；显式指定 3.1.1 是因为 altRelease/SnapshotDeploymentRepository
        # 参数 3.x 才支持（老 Maven 默认绑定的 2.8.2 会忽略）。maven.test.skip：主构建已跑过测试
        build_command += (
            " && mvn -B package org.apache.maven.plugins:maven-deploy-plugin:3.1.1:deploy -Dmaven.test.skip=true"
            f" -DaltReleaseDeploymentRepository=nexus-releases::{settings.release_url}"
            f" -DaltSnapshotDeploymentRepository=nexus-snapshots::{settings.snapshot_url}"
        )

    dockerfile_content = ''
    if item.dockerfile_template_id:
        dockerfile_content = render_for_build(item.dockerfile_template_id, {
            'image_name': item.repo_name,
            'project_type': item.language or '',
            'project_name': tpl.project.name if tpl.project else '',
        })

    safe_branch = branch.replace('/', '-').replace('\\', '-')
    now_ts = datetime.now().strftime('%Y%m%d%H%M%S')
    image_tag = now_ts if re.search(r'[\u4e00-\u9fff]', branch) else f'{safe_branch}-{now_ts}'

    steps_config = {
        'build_mode': 'multi',
        'multi_item_id': item.id,
        'repo_name': item.repo_name,
        'git_docker_image': item.git_docker_image or '',
        'git_url': item.git_url,
        'git_credential_id': item.git_credential_id,
        'build_docker_image': item.build_docker_image or '',
        'build_command': build_command,
        'maven_settings_id': settings_id or None,
        'services': srv_map,
        'dockerfile_content': dockerfile_content,
        'image_name': item.repo_name,
        'image_tag': image_tag,
        'batch_id': batch_id,
        'project_type': 'backend',
        'language': item.language or '',
    }

    from modules.cicd.services.build_service import (
        BUILD_LOG_DIR, _generate_build_no, init_build_steps,
    )
    os.makedirs(BUILD_LOG_DIR, exist_ok=True)
    build_no = _generate_build_no()
    build = Build(
        build_no=build_no,
        project_id=tpl.project_id,
        environment_id=env.id,
        branch=branch,
        project_type='backend',
        language=item.language or '',
        steps_snapshot=json.dumps(steps_config, ensure_ascii=False),
        image_name=item.repo_name,
        image_tag=image_tag,
        batch_id=batch_id,
        status='pending',
        log_file=os.path.join(BUILD_LOG_DIR, f'{build_no}.log'),
        triggered_by=triggered_by,
    )
    db.session.add(build)
    db.session.commit()

    init_build_steps(build_no, 'backend')
    if dispatch:
        from modules.cicd.services.dispatch_service import dispatch_pending
        dispatch_pending()
    return build, None

def trigger_items_build(template_id, item_ids, environment_id, branch, triggered_by, maven_settings_id=None, service_names=None):
    """批量构建多个仓库：分支使用第一个选中仓库的分支（调用方已按此规则传入）。

    多仓发版规则：
    - 一次选多个仓库：只允许一个 branch，所有仓库共用；
    - 一次选一个仓库：前端可选择该仓库自己的 branch。
    """
    from modules.deploy.models import Environment
    tpl = CicdMultiTemplate.query.get(template_id)
    if not tpl:
        return None, '多仓库模板不存在'
    env = Environment.query.get(environment_id) if environment_id else None
    if not env or env.is_deleted:
        return None, '环境不存在'
    if int(env.project_id) != int(tpl.project_id):
        return None, '环境与模板不属于同一项目'

    ids = [int(x) for x in (item_ids or []) if str(x).strip().isdigit()]
    # 选服务即选仓库：以服务名在模板内反查仓库，同仓多服务只产生一个构建；
    # item_ids 仅在未提供服务名时使用（前端映射过期也以服务名为准）
    wanted_services = set(service_names or [])
    if wanted_services:
        all_items = CicdMultiItem.query.filter_by(template_id=tpl.id, enabled=True) \
            .order_by(CicdMultiItem.sort_no.asc(), CicdMultiItem.id.asc()).all()
        ordered = []
        known = set()
        for item in all_items:
            hit = wanted_services & {s.service_name for s in item.services()}
            if hit:
                ordered.append(item)
                known |= hit
        missing = wanted_services - known
        if missing:
            return None, '服务未关联到模板中的仓库: ' + ', '.join(sorted(missing))
        if not ordered:
            return None, '选中的服务没有对应的仓库'
    else:
        if not ids:
            return None, '请至少选择一个仓库'
        items = CicdMultiItem.query.filter(
            CicdMultiItem.template_id == tpl.id,
            CicdMultiItem.id.in_(ids),
            CicdMultiItem.enabled.is_(True),
        ).all()
        by_id = {item.id: item for item in items}
        ordered = [by_id[i] for i in ids if i in by_id]
        if len(ordered) != len(set(ids)):
            return None, '包含不存在、已禁用或不属于该模板的仓库'

    # 先做统一校验，避免批量创建到一半才失败
    for item in ordered:
        if not (item.git_url or '').strip():
            return None, f'仓库「{item.repo_name}」未配置 Git 地址'
        if not (item.build_command or '').strip():
            return None, f'仓库「{item.repo_name}」未配置编译命令'

    branch = (branch or 'master').strip() or 'master'
    # 批次锁：同一环境同一时间只允许一个多仓批次；普通单仓构建仍走自己的旧锁
    from core.redis_client import set_if_absent, cache_get, cache_delete
    env_lock = f'lock:env:{env.project_id}:{env.id}'
    env_owner = cache_get(env_lock)
    if env_owner:
        active = Build.query.filter(
            Build.build_no == env_owner,
            Build.status.in_(('pending', 'running')),
        ).first()
        if active:
            return None, '该环境有单仓构建正在进行，请等待完成后再发版'
        # 残留锁自愈：owner 已终态/记录不存在时清理后继续
        if cache_get(env_lock) == env_owner:
            cache_delete(env_lock)
    batch_no = 'MB' + datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(1000, 9999))
    batch_key = f'lock:batch_env:{env.project_id}:{env.id}'
    if not set_if_absent(batch_key, value=batch_no, ttl=21600000):
        return None, '该环境已有批次构建进行中，请等待完成后再发版'

    selected_service_count = 0
    for item in ordered:
        svcs = item.services()
        if wanted_services:
            svcs = [s for s in svcs if s.service_name in wanted_services]
        selected_service_count += len(svcs)

    batch = CicdBuildBatch(
        batch_no=batch_no,
        project_id=env.project_id,
        environment_id=env.id,
        template_id=tpl.id,
        branch=branch,
        status='pending',
        total_services=selected_service_count,
        total_builds=len(ordered),
        triggered_by=triggered_by,
        started_at=datetime.now(),
    )
    db.session.add(batch)
    db.session.commit()

    builds = []
    for item in ordered:
        item_services_filter = [s.service_name for s in item.services() if s.service_name in wanted_services] if wanted_services else None
        build, err = trigger_item_build(
            item.id, env.id, branch, triggered_by,
            maven_settings_id=maven_settings_id,
            dispatch=False,
            service_names=item_services_filter,
            batch_id=batch.id,
        )
        if err:
            # 已创建的兄弟任务不能留在 pending 里继续执行
            for created in builds:
                created.status = 'cancelled'
                created.finished_at = datetime.now()
            batch.status = 'failed'
            batch.finished_at = datetime.now()
            db.session.commit()
            cache_delete(batch_key)
            return None, f'仓库「{item.repo_name}」: {err}'
        builds.append(build)

    batch.status = 'running'
    db.session.commit()
    if builds:
        from modules.cicd.services.dispatch_service import dispatch_pending
        dispatch_pending()
    return (batch, builds), None


def batch_lock_active(project_id, environment_id):
    """判断该环境是否有进行中的多仓批次；批次已终态/记录丢失时顺带清理残留锁。"""
    from core.redis_client import cache_get, cache_delete
    key = f'lock:batch_env:{project_id}:{environment_id}'
    owner = cache_get(key)
    if not owner:
        return False
    batch = CicdBuildBatch.query.filter_by(batch_no=owner).first()
    if not batch or batch.status in ('success', 'failed', 'cancelled'):
        if cache_get(key) == owner:
            cache_delete(key)
        return False
    return True


def batch_detail(batch):
    """批次详情：按仓库（一个构建）一行展示，附带该仓库包含的服务名。"""
    from modules.cicd.models import Build
    builds = Build.query.filter_by(batch_id=batch.id).order_by(Build.id.asc()).all()
    rows = []
    for b in builds:
        snap = b.get_steps_snapshot()
        services = snap.get('services') or []
        svc_names = [s.get('name') or '' for s in services if s.get('name')]
        repo_name = snap.get('repo_name') or b.image_name or ''
        if not svc_names:
            svc_names = [repo_name]
        progress = 0
        current_step = ''
        try:
            from modules.cicd.services.build_service import get_build_steps
            step_data = get_build_steps(b.build_no) or {}
            step_list = step_data.get('steps') or []
            if step_list:
                # 只把 success 计入进度：失败后未执行/跳过（skipped）的步骤不能算完成，
                # 否则失败构建也会显示 80%+
                done = sum(1 for st in step_list if st.get('status') == 'success')
                progress = int(done * 100 / len(step_list))
                current = next((st for st in step_list if st.get('status') == 'running'), None)
                current_step = (current or {}).get('name', '')
        except Exception:
            pass
        if b.status == 'success':
            progress = 100
        elif b.status in ('pending',):
            progress = 0
        rows.append({
            'build_id': b.id,
            'build_no': b.build_no,
            'repo_name': repo_name,
            'services': svc_names,
            'service_count': len(svc_names),
            'branch': b.branch,
            'status': b.status,
            'progress': progress,
            'current_step': current_step,
            'agent_name': b.agent.name if b.agent else '',
            'started_at': b.started_at.strftime('%Y-%m-%d %H:%M:%S') if b.started_at else None,
            'finished_at': b.finished_at.strftime('%Y-%m-%d %H:%M:%S') if b.finished_at else None,
            'duration': round(b.duration, 1) if b.duration else None,
            'error': b.error_msg or '',
        })
    data = batch.to_dict(include_builds=True)
    data['repos'] = rows
    return data


def finish_batch_if_done(batch_id):
    """child 终态后更新批次终态并释放批次环境锁。"""
    if not batch_id:
        return
    from modules.cicd.models import Build
    from core.redis_client import cache_delete
    batch = CicdBuildBatch.query.get(batch_id)
    if not batch:
        return
    children = Build.query.filter_by(batch_id=batch_id).all()
    if any(b.status in ('pending', 'running') for b in children):
        batch.status = 'running'
    else:
        if children and all(b.status == 'success' for b in children):
            batch.status = 'success'
        elif any(b.status == 'failed' for b in children):
            batch.status = 'failed'
        elif any(b.status == 'cancelled' for b in children):
            batch.status = 'cancelled'
        else:
            batch.status = 'success'
        batch.finished_at = datetime.now()
        cache_delete(f'lock:batch_env:{batch.project_id}:{batch.environment_id}')
    db.session.commit()
