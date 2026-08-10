# -*- coding: utf-8 -*-
"""流程模板管理 API（项目级大模板）"""
from flask import request

from core.response import success_response, error_response
from core.security import require_permission
from core.db import db
from modules.cicd.models import CicdFlowTemplate


@require_permission('page:cicd')
def list_templates():
    """流程模板列表（联表项目名）"""
    templates = CicdFlowTemplate.query.order_by(CicdFlowTemplate.created_at.desc()).all()
    return success_response([t.to_dict() for t in templates])


@require_permission('page:cicd')
def get_template(template_id):
    """获取单个模板"""
    tpl = CicdFlowTemplate.query.get(template_id)
    if not tpl:
        return error_response('模板不存在', 404)
    return success_response(tpl.to_dict())


@require_permission('op:cicd_admin')
def create_template():
    """新增流程模板（每项目仅一个）"""
    data = request.json
    project_id = data.get('project_id')
    if not project_id:
        return error_response('请选择项目', 400)
    if CicdFlowTemplate.query.filter_by(project_id=project_id).first():
        return error_response('该项目已有流程模板', 400)

    project_type = data.get('project_type', 'backend')

    # 后端类型校验：产物目录必填
    if project_type == 'backend':
        artifact_dirs = (data.get('artifact_dirs') or '').strip()
        if not artifact_dirs:
            return error_response('后端项目必须配置产物目录', 400)

    tpl = CicdFlowTemplate(
        project_id=project_id,
        project_type=project_type,
        language=data.get('language', 'java'),
        git_docker_image=data.get('git_docker_image', ''),
        git_url=data.get('git_url', ''),
        git_credential_id=data.get('git_credential_id'),
        build_docker_image=data.get('build_docker_image', ''),
        build_command=data.get('build_command', ''),
        artifact_dirs=data.get('artifact_dirs', ''),
        artifact_dir=data.get('artifact_dir', ''),
        dockerfile_template_id=data.get('dockerfile_template_id'),
        image_name=data.get('image_name', ''),
        description=data.get('description', ''),
    )
    db.session.add(tpl)
    db.session.commit()
    return success_response(tpl.to_dict(), '创建成功')


@require_permission('op:cicd_admin')
def update_template(template_id):
    """编辑流程模板"""
    tpl = CicdFlowTemplate.query.get(template_id)
    if not tpl:
        return error_response('模板不存在', 404)

    data = request.json

    # 基本字段更新
    for field in ('project_type', 'language', 'git_docker_image', 'git_url',
                  'build_docker_image', 'build_command', 'artifact_dirs',
                  'artifact_dir', 'image_name', 'description'):
        if field in data:
            setattr(tpl, field, data[field])

    if 'git_credential_id' in data:
        tpl.git_credential_id = data['git_credential_id']
    if 'dockerfile_template_id' in data:
        tpl.dockerfile_template_id = data['dockerfile_template_id']

    # 后端类型校验
    if tpl.project_type == 'backend':
        if not (tpl.artifact_dirs or '').strip():
            return error_response('后端项目必须配置产物目录', 400)

    db.session.commit()
    return success_response(tpl.to_dict(), '更新成功')


@require_permission('op:cicd_admin')
def delete_template(template_id):
    """删除流程模板"""
    tpl = CicdFlowTemplate.query.get(template_id)
    if not tpl:
        return error_response('模板不存在', 404)
    db.session.delete(tpl)
    db.session.commit()
    return success_response(msg='删除成功')
