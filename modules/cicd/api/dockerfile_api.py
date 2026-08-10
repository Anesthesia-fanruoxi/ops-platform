# -*- coding: utf-8 -*-
"""Dockerfile 模板管理 API"""
from flask import request

from core.response import success_response, error_response
from core.security import require_permission
from core.db import db
from modules.cicd.models import DockerfileTemplate, CicdFlowTemplate
from modules.cicd.services.dockerfile_service import render_dockerfile


@require_permission('page:cicd')
def list_dockerfiles():
    """Dockerfile 模板列表"""
    tpls = DockerfileTemplate.query.order_by(DockerfileTemplate.created_at.desc()).all()
    return success_response([t.to_dict() for t in tpls])


@require_permission('op:cicd_admin')
def create_dockerfile():
    """新增 Dockerfile 模板"""
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return error_response('模板名称不能为空', 400)
    if DockerfileTemplate.query.filter_by(name=name).first():
        return error_response('模板名称已存在', 400)

    tpl = DockerfileTemplate(
        name=name,
        project_type=data.get('project_type', 'java'),
        base_image=data.get('base_image', ''),
        content=data.get('content', ''),
        is_builtin=False,
        description=data.get('description', ''),
    )
    db.session.add(tpl)
    db.session.commit()
    return success_response(tpl.to_dict(), '创建成功')


@require_permission('op:cicd_admin')
def update_dockerfile(tpl_id):
    """编辑 Dockerfile 模板"""
    tpl = DockerfileTemplate.query.get(tpl_id)
    if not tpl:
        return error_response('模板不存在', 404)

    data = request.json
    if 'name' in data and data['name'].strip():
        tpl.name = data['name'].strip()
    if 'project_type' in data:
        tpl.project_type = data['project_type']
    if 'description' in data:
        tpl.description = data['description']
    if 'base_image' in data:
        tpl.base_image = data['base_image']
    if 'content' in data:
        tpl.content = data['content']

    db.session.commit()
    return success_response(tpl.to_dict(), '更新成功')


@require_permission('op:cicd_admin')
def delete_dockerfile(tpl_id):
    """删除 Dockerfile 模板，关联流程模板的 dockerfile_template_id 置空"""
    tpl = DockerfileTemplate.query.get(tpl_id)
    if not tpl:
        return error_response('模板不存在', 404)
    # 置空引用该模板的流程记录
    CicdFlowTemplate.query.filter_by(dockerfile_template_id=tpl_id).update(
        {'dockerfile_template_id': None}
    )
    db.session.delete(tpl)
    db.session.commit()
    return success_response(msg='删除成功')


@require_permission('page:cicd')
def preview_dockerfile(tpl_id):
    """预览渲染后的 Dockerfile（用示例变量）"""
    tpl = DockerfileTemplate.query.get(tpl_id)
    if not tpl:
        return error_response('模板不存在', 404)
    sample_vars = {
        'base_image': tpl.base_image or 'testhub.hzbxhd.com/library/rocky:9.3-openjdk17-zh',
        'artifact_name': 'my-app',
        'jar_name': 'my-modules-app',
        'workdir': '/data/project/my-app',
        'java_opts': '-server -Xms2g -Xmx8g -XX:CompressedClassSpaceSize=2g -XX:MaxMetaspaceSize=2g -XX:+UseG1GC',
        'port': '8080',
        'project_name': 'sample-project',
    }
    rendered = render_dockerfile(tpl.content, sample_vars)
    return success_response({'content': rendered})
