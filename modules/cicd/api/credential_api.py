# -*- coding: utf-8 -*-
"""凭据管理 API"""
from flask import request, g

from core.response import success_response, error_response
from core.security import require_permission
from core.db import db
from modules.cicd.models import GitCredential, CicdFlowTemplate
from modules.cicd.services.credential_service import (
    encrypt_secret, test_git_connection
)


@require_permission('op:cicd_admin')
def list_credentials():
    """凭据列表"""
    creds = GitCredential.query.order_by(GitCredential.created_at.desc()).all()
    return success_response([c.to_dict() for c in creds])


@require_permission('op:cicd_admin')
def create_credential():
    """新增凭据"""
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return error_response('凭据名称不能为空', 400)
    if GitCredential.query.filter_by(name=name).first():
        return error_response('凭据名称已存在', 400)

    cred = GitCredential(
        name=name,
        type=data.get('type', 'password'),
        username=data.get('username', ''),
        secret=encrypt_secret(data.get('secret', '')),
        url=data.get('url', '').strip(),
        description=data.get('description', ''),
    )
    db.session.add(cred)
    db.session.commit()
    return success_response(cred.to_dict(), '创建成功')


@require_permission('op:cicd_admin')
def update_credential(cred_id):
    """编辑凭据（secret 为空则不修改）"""
    cred = GitCredential.query.get(cred_id)
    if not cred:
        return error_response('凭据不存在', 404)

    data = request.json
    if 'name' in data and data['name'].strip():
        exists = GitCredential.query.filter(
            GitCredential.name == data['name'].strip(), GitCredential.id != cred_id
        ).first()
        if exists:
            return error_response('凭据名称已存在', 400)
        cred.name = data['name'].strip()
    if 'type' in data:
        cred.type = data['type']
    if 'username' in data:
        cred.username = data['username']
    if 'description' in data:
        cred.description = data['description']
    if 'url' in data:
        cred.url = data['url'].strip()
    # secret 仅写不回填：前端传空串或不传则不改
    if data.get('secret'):
        cred.secret = encrypt_secret(data['secret'])

    db.session.commit()
    return success_response(cred.to_dict(), '更新成功')


@require_permission('op:cicd_admin')
def delete_credential(cred_id):
    """删除凭据，关联流程模板的 git_credential_id 置空"""
    cred = GitCredential.query.get(cred_id)
    if not cred:
        return error_response('凭据不存在', 404)
    CicdFlowTemplate.query.filter_by(git_credential_id=cred_id).update(
        {'git_credential_id': None}
    )
    db.session.delete(cred)
    db.session.commit()
    return success_response(msg='删除成功')


@require_permission('op:cicd_admin')
def test_credential(cred_id):
    """测试凭据连通性（需传 git_url）"""
    data = request.json or {}
    git_url = data.get('git_url', '')
    if not git_url:
        return error_response('请提供 git_url 用于测试', 400)
    ok, msg = test_git_connection(git_url, cred_id)
    if ok:
        return success_response(msg=msg)
    return error_response(msg, 400)
