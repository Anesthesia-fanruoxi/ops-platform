# -*- coding: utf-8 -*-
"""
项目管理接口处理函数
"""
from flask import request
from core.db import db
from modules.deploy.models import Project, Environment
from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.api.shared import get_ignored_projects


@require_permission('page:projects')
def list_projects():
    """列出所有项目（过滤忽略的项目，附带环境数量）"""
    ignored = get_ignored_projects()
    projects = Project.query.all()
    result = []
    for p in projects:
        if p.name in ignored:
            continue
        env_count = Environment.query.filter_by(project_id=p.id).count()
        result.append({
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'env_count': env_count,
            'created_at': p.created_at.strftime('%Y-%m-%d %H:%M:%S') if p.created_at else None
        })
    return success_response(result)


@require_permission('page:projects')
def update_project():
    """
    更新项目信息（项目名称不可更改）

    请求体:
    {
        "id": 1,
        "description": "新的描述"
    }
    """
    data = request.json
    project_id = data.get('id')

    if not project_id:
        return error_response('项目ID不能为空', 400)

    project = Project.query.get(project_id)
    if not project:
        return error_response(f'项目不存在', 404)

    # 更新描述
    if 'description' in data:
        project.description = data['description']

    db.session.commit()
    return success_response(project.to_dict(), '项目更新成功')


@require_permission('page:projects')
def refresh_projects():
    """清理无任何环境的项目记录"""
    ignored = get_ignored_projects()

    removed = []
    projects = Project.query.all()
    for p in projects:
        if p.name in ignored:
            continue
        env_count = Environment.query.filter_by(project_id=p.id).count()
        if env_count == 0:
            db.session.delete(p)
            removed.append(p.name)
    db.session.commit()

    if removed:
        return success_response({'removed': removed, 'count': len(removed)},
                                f'已清理 {len(removed)} 个空项目: {", ".join(removed)}')
    return success_response({'removed': [], 'count': 0}, '没有需要清理的空项目')
