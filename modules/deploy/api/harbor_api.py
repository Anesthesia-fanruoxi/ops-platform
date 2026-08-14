# -*- coding: utf-8 -*-
"""
Harbor管理接口处理函数
"""
from flask import request
from modules.deploy.services.harbor_client import HarborClient
from core.response import success_response, error_response
from core.security import require_permission


def get_harbor_client():
    """获取Harbor客户端（优先从数据库读取配置）"""
    from modules.system.models import Setting

    def _get_setting(key, default):
        try:
            s = Setting.query.filter_by(key=key).first()
            return s.value if s and s.value else default
        except Exception:
            return default

    return HarborClient(
        harbor_url=_get_setting('harbor_url', ''),
        username=_get_setting('harbor_user', ''),
        password=_get_setting('harbor_pass', ''),
    )


@require_permission('op:deploy_project')
def create_project():
    """
    创建Harbor项目并设置清理策略

    请求体:
    {
        "project_name": "jieyihua-test",
        "public": false,
        "cleanup": {
            "enabled": true,
            "keep_versions": 3,
            "cron": "0 0 * * * *"
        }
    }
    """
    try:
        data = request.json

        if not data.get('project_name'):
            return error_response('project_name is required', 400)

        harbor = get_harbor_client()

        # 检查项目是否已存在
        existing_project = harbor.get_project(data['project_name'])
        if existing_project:
            return error_response(f"Project '{data['project_name']}' already exists", 409)

        # 创建项目
        result = harbor.create_project(
            project_name=data['project_name'],
            public=data.get('public', True),
            metadata=data.get('metadata', {})
        )

        if not result['success']:
            return error_response(result['message'], result['status_code'])

        # 设置清理策略
        cleanup_config = data.get('cleanup', {})
        if cleanup_config.get('enabled', True):
            keep_raw = _get_setting('harbor_cleanup_keep_versions', '')
            keep_versions = cleanup_config.get('keep_versions', int(keep_raw) if keep_raw else 3)
            cron = cleanup_config.get('cron', _get_setting('harbor_cleanup_cron', '') or '0 0 * * * *')

            import time
            time.sleep(2)
            proj_info = harbor.get_project(data['project_name'])
            project_id = proj_info.get('project_id') if proj_info else None
            retention_ref = project_id if project_id else data['project_name']

            harbor.create_retention_policy(
                project_name_or_id=retention_ref,
                keep_recent=keep_versions,
                cron=cron
            )

        return success_response({
            'project_name': data['project_name'],
            'cleanup': {
                'enabled': True,
                'keep_versions': cleanup_config.get('keep_versions', 3),
                'cron': cleanup_config.get('cron', '0 0 * * * *')
            }
        }, 'Project created successfully')

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('page:create')
def list_projects():
    """
    获取项目列表

    查询参数:
    - page: 页码，默认1
    - page_size: 每页数量，默认10
    - q: 查询条件
    """
    try:
        harbor = get_harbor_client()
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 10, type=int)
        q = request.args.get('q')

        projects = harbor.get_projects(page=page, page_size=page_size, q=q)
        return success_response(projects)

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('page:create')
def get_project(project_name):
    """获取单个项目信息"""
    try:
        harbor = get_harbor_client()
        project = harbor.get_project(project_name)

        if not project:
            return error_response(f"Project '{project_name}' not found", 404)

        return success_response(project)

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def delete_project(project_name):
    """删除项目"""
    try:
        harbor = get_harbor_client()
        result = harbor.delete_project(project_name)

        if not result['success']:
            return error_response('Failed to delete project', result['status_code'])

        return success_response(None, f"Project '{project_name}' deleted successfully")

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('page:create')
def list_repositories(project_name):
    """获取项目下的仓库列表"""
    try:
        harbor = get_harbor_client()
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 10, type=int)

        repos = harbor.get_repositories(project_name, page=page, page_size=page_size)
        return success_response(repos)

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('page:create')
def list_artifacts(project_name, repository_name):
    """获取镜像制品列表"""
    try:
        harbor = get_harbor_client()
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 10, type=int)

        artifacts = harbor.get_artifacts(project_name, repository_name, page=page, page_size=page_size)
        return success_response(artifacts)

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def setup_cleanup():
    """
    为现有项目设置清理策略

    请求体:
    {
        "project_name": "jieyihua-test",
        "keep_versions": 3,
        "cron": "0 0 * * * *"
    }
    """
    try:
        data = request.json

        if not data.get('project_name'):
            return error_response('project_name is required', 400)

        harbor = get_harbor_client()

        # 检查项目是否存在
        project = harbor.get_project(data['project_name'])
        if not project:
            return error_response(f"Project '{data['project_name']}' not found", 404)

        keep_versions = data.get('keep_versions', 3)
        cron = data.get('cron', '0 0 * * * *')

        # 获取项目ID
        project_id = project.get('project_id')
        retention_ref = project_id if project_id else data['project_name']

        harbor.create_retention_policy(
            project_name_or_id=retention_ref,
            keep_recent=keep_versions,
            cron=cron
        )

        return success_response({
            'project_name': data['project_name'],
            'keep_versions': keep_versions,
            'cron': cron
        }, 'Cleanup policy configured successfully')

    except Exception as e:
        return error_response(str(e), 500)
