# -*- coding: utf-8 -*-
"""流程模板管理 API（项目级大模板）"""
import json

from flask import request

from core.response import success_response, error_response
from core.security import require_permission
from core.db import db
from core.audit import record_audit_diff
from modules.cicd.models import CicdFlowTemplate


def _normalize_configs(data):
    """归一化前后端双份配置（configs: {"backend": {...}, "frontend": {...}}）"""
    cfg = data.get('configs') or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        'backend': cfg.get('backend') or {},
        'frontend': cfg.get('frontend') or {},
    }


@require_permission('page:cicd')
def list_templates():
    """流程模板列表（精简字段，详情走 GET /<id>）"""
    templates = CicdFlowTemplate.query.order_by(CicdFlowTemplate.created_at.desc()).all()
    return success_response([{
        'id': t.id,
        'project_name': t.project.name if t.project else '',
        'project_type': t.project_type,
        'language': (t.configs_dict().get(t.project_type) or {}).get('language', ''),
        'git_url': (t.configs_dict().get(t.project_type) or {}).get('git_url', ''),
        'build_docker_image': (t.configs_dict().get(t.project_type) or {}).get('build_docker_image', ''),
        'description': t.description,
        'updated_at': t.updated_at.strftime('%Y-%m-%d %H:%M:%S') if t.updated_at else None,
    } for t in templates])


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

    configs = _normalize_configs(data)

    # 后端类型校验：产物目录必填
    backend_cfg = configs['backend']
    if project_type == 'backend':
        artifact_dirs = (backend_cfg.get('artifact_dirs') or '').strip()
        if not artifact_dirs:
            return error_response('后端项目必须配置产物目录', 400)

    tpl = CicdFlowTemplate(
        project_id=project_id,
        project_type=project_type,
        description=data.get('description', ''),
        configs=json.dumps(configs, ensure_ascii=False),
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

    _old_cfg = tpl.configs_dict()
    data = request.json

    # 前后端双份配置（configs JSON）为唯一数据源
    if data.get('configs') is not None:
        tpl.configs = json.dumps(_normalize_configs(data), ensure_ascii=False)

    # 通用字段（configs 为唯一数据源，仅存类型/描述）
    for field in ('project_type', 'description'):
        if field in data:
            setattr(tpl, field, data[field])

    # 后端类型校验（以 configs.backend 为准）
    backend_cfg = tpl.configs_dict()['backend']
    if tpl.project_type == 'backend':
        if not (backend_cfg.get('artifact_dirs') or '').strip():
            return error_response('后端项目必须配置产物目录', 400)

    db.session.commit()
    _ptype = tpl.project_type or 'backend'
    _new_cfg = tpl.configs_dict()
    _fields = ('language', 'git_docker_image', 'git_url', 'git_credential_id', 'build_docker_image',
               'build_command', 'artifact_dirs', 'artifact_dir', 'dockerfile_template_id')
    record_audit_diff('template', 'update', tpl.id,
                      _old_cfg.get(_ptype) or {}, _new_cfg.get(_ptype) or {}, fields=_fields)
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
