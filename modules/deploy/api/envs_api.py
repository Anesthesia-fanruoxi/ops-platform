# -*- coding: utf-8 -*-
"""
环境管理接口处理函数 - 环境查询、验证、详情
"""
import os
import json
import shutil
import yaml
from flask import request
from core.response import success_response, error_response
from core.security import require_permission
from core.db import db
from modules.deploy.api.shared import get_output_dir, get_ignored_projects


# ─── 环境列表 ─────────────────────────────────────────────

def _get_env_counts(project_name=None):
    """获取运行中和已删除环境的数量（过滤忽略项目）"""
    from modules.deploy.models import Environment, Project
    from sqlalchemy import func
    ignored = get_ignored_projects()

    base_q = db.session.query(func.count(Environment.id)).join(Project, Environment.project_id == Project.id)
    if project_name:
        base_q = base_q.filter(Project.name == project_name)
    if ignored:
        base_q = base_q.filter(~Project.name.in_(ignored))

    running = base_q.filter((Environment.is_deleted == False) | (Environment.is_deleted == None)).scalar() or 0
    deleted = base_q.filter(Environment.is_deleted == True).scalar() or 0
    return running, deleted


@require_permission('page:manage')
def list_environments():
    """查询数据库，返回环境列表（支持按项目过滤，排除已删除，过滤忽略项目，附加最后构建信息）"""
    from modules.deploy.models import Environment, Project
    from modules.cicd.models import Build

    project_name = request.args.get('project', '')
    show_deleted = request.args.get('show_deleted', 'false').lower() == 'true'
    ignored = get_ignored_projects()

    query = Environment.query
    if not show_deleted:
        query = query.filter((Environment.is_deleted == False) | (Environment.is_deleted == None))
    if project_name:
        project = Project.query.filter_by(name=project_name).first()
        if project:
            query = query.filter_by(project_id=project.id)

    envs = query.all()

    # 批量查询每个环境的最后构建记录（按 前后端 分层，避免 N+1）
    last_builds = {}
    if not show_deleted:
        env_ids = [e.id for e in envs]
        if env_ids:
            from sqlalchemy import func
            subq = db.session.query(
                Build.environment_id,
                Build.project_type,
                func.max(Build.created_at).label('max_at')
            ).filter(Build.environment_id.in_(env_ids)).group_by(Build.environment_id, Build.project_type).subquery()

            builds = db.session.query(Build).join(
                subq,
                (Build.environment_id == subq.c.environment_id) &
                (Build.project_type == subq.c.project_type) &
                (Build.created_at == subq.c.max_at)
            ).all()
            for b in builds:
                last_builds.setdefault(b.environment_id, {})[b.project_type or 'backend'] = b

    result = []
    for env in envs:
        proj_name = env.project.name if env.project else ''
        if proj_name in ignored:
            continue
        item = {
            'id': env.id,
            'project_id': env.project_id,
            'project': proj_name,
            'environment': env.name,
            'domain': env.domain or '',
            'port_start': env.port_start,
            'nacos_namespace': env.nacos_namespace or '',
            'is_deleted': env.is_deleted,
            'deleted_at': env.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if env.deleted_at else None,
            'created_at': env.created_at.strftime('%Y-%m-%d %H:%M:%S') if env.created_at else None
        }
        # 附加最后构建摘要（按 前后端 分层；顶层 last_build 兼容保留为后端摘要）
        if not show_deleted:
            lb_map = last_builds.get(env.id, {})
            def _summary(lb):
                if not lb:
                    return None
                return {
                    'id': lb.id,
                    'build_no': lb.build_no,
                    'status': lb.status,
                    'branch': lb.branch,
                    'triggered_by': lb.triggered_by,
                    'created_at': lb.created_at.strftime('%Y-%m-%d %H:%M:%S') if lb.created_at else None,
                }
            item['builds'] = {
                'backend': _summary(lb_map.get('backend')),
                'frontend': _summary(lb_map.get('frontend')),
            }
            item['last_build'] = item['builds']['backend']  # 兼容旧引用
        result.append(item)
    running_count, deleted_count = _get_env_counts(project_name or None)
    return success_response({
        'list': result,
        'running_count': running_count,
        'deleted_count': deleted_count
    })


@require_permission('page:manage')
def list_deleted_environments():
    """查询已删除的环境列表（过滤忽略的项目）"""
    from modules.deploy.models import Environment, Project

    project_name = request.args.get('project', '')
    ignored = get_ignored_projects()

    query = Environment.query.filter_by(is_deleted=True)
    if project_name:
        project = Project.query.filter_by(name=project_name).first()
        if project:
            query = query.filter_by(project_id=project.id)

    envs = query.all()
    result = []
    for env in envs:
        proj_name = env.project.name if env.project else ''
        if proj_name in ignored:
            continue
        result.append({
            'id': env.id,
            'project': proj_name,
            'environment': env.name,
            'domain': env.domain or '',
            'port_start': env.port_start,
            'nacos_namespace': env.nacos_namespace or '',
            'deleted_at': env.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if env.deleted_at else None,
            'created_at': env.created_at.strftime('%Y-%m-%d %H:%M:%S') if env.created_at else None
        })
    running_count, deleted_count = _get_env_counts(project_name or None)
    return success_response({
        'list': result,
        'running_count': running_count,
        'deleted_count': deleted_count
    })


# ─── 验证接口 ─────────────────────────────────────────────

@require_permission('page:manage')
def validate_project():
    """验证项目名称是否存在"""
    from modules.deploy.models import Project
    name = request.args.get('name', '').strip()
    if not name:
        return success_response({'exists': False})

    exists = Project.query.filter_by(name=name).first() is not None
    return success_response({'exists': exists, 'name': name})


@require_permission('page:manage')
def validate_environment():
    """验证环境名称是否存在"""
    from modules.deploy.models import Environment, Project
    project_name = request.args.get('project', '').strip()
    env_name = request.args.get('env', '').strip()

    if not project_name or not env_name:
        return success_response({'exists': False})

    project = Project.query.filter_by(name=project_name).first()
    if not project:
        return success_response({'exists': False})

    exists = Environment.query.filter_by(project_id=project.id, name=env_name).first() is not None
    return success_response({'exists': exists, 'project': project_name, 'env': env_name})


@require_permission('page:manage')
def validate_service():
    """验证服务是否存在（数据库 deploy_config + 本地 YAML 文件）"""
    service_name = request.args.get('name', '').strip()
    project = request.args.get('project', '').strip()
    env = request.args.get('env', '').strip()

    if not service_name or not project or not env:
        return success_response({'exists': False})

    # 1. 数据库：环境 deploy_config.services 中是否已有同名服务（权威来源）
    from modules.deploy.models import Environment, Project
    env_obj = Environment.query.join(Project).filter(
        Project.name == project,
        Environment.name == env,
        (Environment.is_deleted == False) | (Environment.is_deleted == None)  # noqa: E712
    ).first()
    if env_obj and env_obj.deploy_config:
        try:
            cfg = json.loads(env_obj.deploy_config)
            for s in cfg.get('services', []):
                sname = s.get('name', s.get('app_name', '')) if isinstance(s, dict) else str(s)
                if sname == service_name:
                    return success_response({'exists': True, 'source': 'database'})
        except Exception:
            pass

    # 2. 本地 YAML 输出目录：deployment/service 下是否存在对应文件
    from modules.system.settings_service import get_setting
    output_dir = get_setting('yaml_output_dir', '')
    deploy_file = os.path.join(output_dir, f'{project}-{env}', 'deployment', f'{project}-{service_name}.yaml')
    svc_file = os.path.join(output_dir, f'{project}-{env}', 'service', f'{project}-{service_name}.yaml')

    if os.path.exists(deploy_file) or os.path.exists(svc_file):
        return success_response({'exists': True, 'source': 'file'})
    return success_response({'exists': False})


# ─── 源环境信息 ───────────────────────────────────────────

@require_permission('page:manage')
def get_source_env_info():
    """获取源环境的服务和中间件信息（从目录读取文件名）"""
    environment = request.args.get('environment', '')
    if not environment:
        return error_response('参数不能为空', 400)

    output_dir = get_output_dir()
    base_path = os.path.join(output_dir, environment)

    if not os.path.exists(base_path):
        return error_response(f'目录 {environment} 不存在', 404)

    # 读取 deployment 文件名（即服务列表）
    services = []
    deploy_dir = os.path.join(base_path, 'deployment')
    if os.path.exists(deploy_dir):
        for f in os.listdir(deploy_dir):
            if f.endswith('.yaml') or f.endswith('.yml'):
                # 提取服务名：ysh-app.yaml -> app
                svc_name = f.replace('.yaml', '').replace('.yml', '')
                # 去掉项目前缀
                if '-' in svc_name:
                    svc_name = svc_name.split('-', 1)[1]
                services.append({
                    'name': svc_name,
                    'xms': 2,
                    'xmx': 8,
                    'replicas': 1
                })

    # 读取 middleware 文件名
    middleware = []
    mw_dir = os.path.join(base_path, 'middleware')
    if os.path.exists(mw_dir):
        for f in os.listdir(mw_dir):
            if f.endswith('.yaml') or f.endswith('.yml'):
                mw_name = f.replace('.yaml', '').replace('.yml', '')
                middleware.append(mw_name)

    return success_response({
        'environment': environment,
        'services': services,
        'middleware': middleware
    })


# ─── 可用端口 ─────────────────────────────────────────────

@require_permission('page:manage')
def get_available_port():
    """获取可用的起始端口"""
    from modules.deploy.models import Environment

    # 端口范围 30000-49000
    PORT_RANGE_START = 30000
    PORT_RANGE_END = 49000
    PORT_BLOCK_SIZE = 100  # 每个环境占用100个端口

    # 查询所有已分配的端口范围
    envs = Environment.query.all()
    occupied_ranges = []
    for env in envs:
        if env.port_start:
            occupied_ranges.append({
                'start': env.port_start,
                'end': env.port_start + PORT_BLOCK_SIZE - 1,
                'env': f"{env.project.name if env.project else ''}-{env.name}"
            })

    # 按起始端口排序
    occupied_ranges.sort(key=lambda x: x['start'])

    # 找到可用的端口段
    available_port = PORT_RANGE_START
    for range_item in occupied_ranges:
        if available_port < range_item['start']:
            # 这个区间之前有空闲
            break
        available_port = max(available_port, range_item['end'] + 1)

    # 确保不超过范围
    if available_port > PORT_RANGE_END:
        available_port = None

    return success_response({
        'available_port': available_port,
        'port_range': f"{PORT_RANGE_START}-{PORT_RANGE_END}",
        'occupied_count': len(occupied_ranges),
        'occupied_ranges': occupied_ranges[:10]  # 只返回前10条
    })


# ─── 环境详情 ─────────────────────────────────────────────

@require_permission('page:manage')
def get_environment_detail():
    """获取环境详细信息，解析目录下的YAML文件"""
    environment = request.args.get('environment', '')
    if not environment or '-' not in environment:
        return error_response('参数格式错误，应为 environment=project-env', 400)

    output_dir = get_output_dir()
    base_path = os.path.join(output_dir, environment)
    if not os.path.exists(base_path):
        return error_response(f'环境 {environment} 不存在', 404)

    result = {
        'environment': environment,
        'path': base_path,
        'deployments': [],
        'services': [],
        'middleware': []
    }

    # 读取 Deployment 目录
    deploy_dir = os.path.join(base_path, 'deployment')
    if os.path.exists(deploy_dir):
        for f in sorted(os.listdir(deploy_dir)):
            if f.endswith('.yaml') or f.endswith('.yml'):
                try:
                    with open(os.path.join(deploy_dir, f), 'r', encoding='utf-8') as fp:
                        doc = yaml.safe_load(fp)
                    if doc and doc.get('kind') == 'Deployment':
                        spec = doc.get('spec', {})
                        template = spec.get('template', {})
                        containers = template.get('spec', {}).get('containers', [])
                        # 获取主容器的镜像
                        main_image = ''
                        for c in containers:
                            if c.get('name') != 'filebeat':
                                main_image = c.get('image', '')
                                break
                        if not main_image and containers:
                            main_image = containers[0].get('image', '')

                        result['deployments'].append({
                            'name': doc.get('metadata', {}).get('name', f.replace('.yaml', '')),
                            'replicas': spec.get('replicas', 1),
                            'image': main_image,
                            'namespace': doc.get('metadata', {}).get('namespace', '')
                        })
                except Exception as e:
                    pass

    # 读取 Service 目录
    svc_dir = os.path.join(base_path, 'service')
    if os.path.exists(svc_dir):
        for f in sorted(os.listdir(svc_dir)):
            if f.endswith('.yaml') or f.endswith('.yml'):
                try:
                    with open(os.path.join(svc_dir, f), 'r', encoding='utf-8') as fp:
                        doc = yaml.safe_load(fp)
                    if doc and doc.get('kind') == 'Service':
                        ports = doc.get('spec', {}).get('ports', [])
                        # 解析每个端口
                        port_list = []
                        for p in ports:
                            port_list.append({
                                'name': p.get('name', ''),
                                'port': p.get('port', ''),
                                'nodePort': p.get('nodePort', ''),
                                'targetPort': p.get('targetPort', '')
                            })
                        result['services'].append({
                            'name': doc.get('metadata', {}).get('name', f.replace('.yaml', '')),
                            'type': doc.get('spec', {}).get('type', ''),
                            'ports': port_list
                        })
                except Exception as e:
                    pass

    # 读取 Middleware 目录
    mw_dir = os.path.join(base_path, 'middleware')
    if os.path.exists(mw_dir):
        for f in sorted(os.listdir(mw_dir)):
            if f.endswith('.yaml') or f.endswith('.yml'):
                try:
                    with open(os.path.join(mw_dir, f), 'r', encoding='utf-8') as fp:
                        content = fp.read()
                    docs = list(yaml.safe_load_all(content))
                    # 查找 NodePort 类型的 Service，获取端口
                    node_port = ''
                    for doc in docs:
                        if doc and doc.get('kind') == 'Service':
                            svc_spec = doc.get('spec', {})
                            if svc_spec.get('type') == 'NodePort':
                                svc_ports = svc_spec.get('ports', [])
                                if svc_ports:
                                    node_port = str(svc_ports[0].get('nodePort', ''))
                                break
                    result['middleware'].append({
                        'name': f.replace('.yaml', '').replace('.yml', ''),
                        'nodePort': node_port
                    })
                except Exception as e:
                    pass

    # 统计信息
    result['summary'] = {
        'deployment_count': len(result['deployments']),
        'service_count': len(result['services']),
        'middleware_count': len(result['middleware'])
    }

    # 中间件凭据（从系统设置读取）
    from modules.system.settings_service import get_setting
    def _setting_val(key):
        return get_setting(key, '')

    result['credentials'] = {
        'mysql': {'user': _setting_val('mysql_default_user'), 'pass': _setting_val('mysql_default_pass')},
        'redis': {'user': _setting_val('redis_user'), 'pass': _setting_val('redis_pass')},
        'rabbitmq': {'user': _setting_val('rabbitmq_user'), 'pass': _setting_val('rabbitmq_pass')},
        'nacos': {'user': _setting_val('nacos_user'), 'pass': _setting_val('nacos_pass')},
    }

    return success_response(result)
