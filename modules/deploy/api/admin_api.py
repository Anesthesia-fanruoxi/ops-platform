# -*- coding: utf-8 -*-
"""
项目和环境管理接口处理函数
"""
from flask import request
from core.db import db
from modules.deploy.models import Project, Environment
from core.response import success_response, error_response
from modules.deploy.api.shared import get_ignored_projects


# ==================== 项目管理 ====================

def list_projects():
    """获取项目列表（过滤忽略的项目）"""
    ignored = get_ignored_projects()
    projects = Project.query.all()
    result = [p.to_dict() for p in projects if p.name not in ignored]
    return success_response(result)


def create_project():
    """创建项目"""
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return error_response('项目名称不能为空', 400)

    if Project.query.filter_by(name=name).first():
        return error_response(f"项目 '{name}' 已存在", 409)

    project = Project(name=name, description=data.get('description', ''))
    db.session.add(project)
    db.session.commit()
    return success_response(project.to_dict(), '项目创建成功')


def delete_project(project_id):
    """删除项目"""
    project = Project.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()
    return success_response(None, '项目删除成功')


# ==================== 环境管理 ====================

def list_environments(project_id):
    """获取项目的环境列表"""
    envs = Environment.query.filter_by(project_id=project_id).all()
    return success_response([e.to_dict() for e in envs])


def get_environment(env_id):
    """获取单个环境详情"""
    env = Environment.query.get_or_404(env_id)
    return success_response(env.to_dict())


def update_environment(env_id):
    """更新环境"""
    env = Environment.query.get_or_404(env_id)
    data = request.json

    if 'name' in data:
        env.name = data['name']
    if 'domain' in data:
        env.domain = data['domain']
    if 'port_start' in data:
        env.port_start = data['port_start']

    db.session.commit()
    return success_response(env.to_dict(), '环境更新成功')


def delete_environment(env_id):
    """删除环境"""
    env = Environment.query.get_or_404(env_id)
    db.session.delete(env)
    db.session.commit()
    return success_response(None, '环境删除成功')
