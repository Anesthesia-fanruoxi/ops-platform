# -*- coding: utf-8 -*-
"""Maven Settings 管理：settings.xml 加密落库，构建时按模板/构建选择下发"""
import xml.etree.ElementTree as ET

from flask import request

from core.db import db
from core.response import success_response, error_response
from core.security import require_permission
from modules.cicd.models import MavenSettings
from modules.cicd.services.credential_service import encrypt_secret, decrypt_secret


def _validate_payload(data):
    name = (data.get('name') or '').strip()
    if not name:
        return None, '请填写名称'
    if len(name) > 100:
        return None, '名称不能超过 100 个字符'
    content = data.get('content') or ''
    if not content.strip():
        return None, '请填写 settings.xml 内容'
    if len(content) > 1024 * 1024:
        return None, 'settings.xml 内容不能超过 1MB'
    try:
        ET.fromstring(content.lstrip('\ufeff'))
    except Exception:
        return None, 'settings.xml 不是合法 XML'
    release_url = (data.get('release_url') or '').strip()
    snapshot_url = (data.get('snapshot_url') or '').strip()
    for label, url in (('release 发布地址', release_url), ('snapshot 发布地址', snapshot_url)):
        if not url:
            continue
        if not url.startswith(('http://', 'https://')):
            return None, f'{label}必须以 http:// 或 https:// 开头'
        if len(url) > 300:
            return None, f'{label}不能超过 300 个字符'
    return {
        'name': name,
        'description': (data.get('description') or '').strip()[:200],
        'content': content,
        'release_url': release_url,
        'snapshot_url': snapshot_url,
    }, None


@require_permission('page:cicd')
def list_settings():
    rows = MavenSettings.query.order_by(MavenSettings.updated_at.desc()).all()
    return success_response([r.to_dict() for r in rows])


@require_permission('op:cicd_admin')
def get_setting(setting_id):
    row = MavenSettings.query.get(setting_id)
    if not row:
        return error_response('Maven Settings 不存在', 404)
    data = row.to_dict()
    data['content'] = decrypt_secret(row.content)
    return success_response(data)


@require_permission('op:cicd_admin')
def create_setting():
    payload, err = _validate_payload(request.json or {})
    if err:
        return error_response(err, 400)
    if MavenSettings.query.filter_by(name=payload['name']).first():
        return error_response('名称已存在', 409)
    row = MavenSettings(
        name=payload['name'],
        description=payload['description'],
        content=encrypt_secret(payload['content']),
        release_url=payload['release_url'],
        snapshot_url=payload['snapshot_url'],
    )
    db.session.add(row)
    db.session.commit()
    return success_response(row.to_dict(), '创建成功')


@require_permission('op:cicd_admin')
def update_setting(setting_id):
    row = MavenSettings.query.get(setting_id)
    if not row:
        return error_response('Maven Settings 不存在', 404)
    payload, err = _validate_payload(request.json or {})
    if err:
        return error_response(err, 400)
    dup = MavenSettings.query.filter(
        MavenSettings.name == payload['name'], MavenSettings.id != row.id
    ).first()
    if dup:
        return error_response('名称已存在', 409)
    row.name = payload['name']
    row.description = payload['description']
    row.content = encrypt_secret(payload['content'])
    row.release_url = payload['release_url']
    row.snapshot_url = payload['snapshot_url']
    db.session.commit()
    return success_response(row.to_dict(), '保存成功')


@require_permission('op:cicd_admin')
def delete_setting(setting_id):
    row = MavenSettings.query.get(setting_id)
    if not row:
        return error_response('Maven Settings 不存在', 404)
    from modules.cicd.multi_models import CicdMultiTemplate
    used = CicdMultiTemplate.query.filter_by(maven_settings_id=setting_id).count()
    if used:
        return error_response(f'被 {used} 个多仓库模板引用，请先解除绑定', 400)
    db.session.delete(row)
    db.session.commit()
    return success_response(msg='删除成功')
