# -*- coding: utf-8 -*-
"""多仓库模板 API（独立于单仓流程模板）"""
from flask import request

from core.response import success_response, error_response
from core.security import require_permission, require_any_permission
from modules.cicd.multi_models import CicdMultiTemplate, CicdBuildBatch
from modules.cicd.services import multi_repo_service


@require_permission('page:cicd')
def list_multi_templates():
    templates = CicdMultiTemplate.query.order_by(CicdMultiTemplate.updated_at.desc()).all()
    return success_response([t.to_dict(include_items=False) for t in templates])


@require_permission('page:cicd')
def get_multi_template(tpl_id):
    tpl = multi_repo_service.get_template(tpl_id)
    if not tpl:
        return error_response('模板不存在', 404)
    return success_response(tpl.to_dict(include_items=True))


@require_permission('op:cicd_admin')
def create_multi_template():
    tpl, err = multi_repo_service.save_template(request.json or {})
    if err:
        return error_response(err, 400)
    return success_response(tpl.to_dict(include_items=True), '创建成功')


@require_permission('op:cicd_admin')
def update_multi_template(tpl_id):
    tpl, err = multi_repo_service.save_template(request.json or {}, tpl_id=tpl_id)
    if err:
        return error_response(err, 400)
    return success_response(tpl.to_dict(include_items=True), '保存成功')


@require_permission('op:cicd_admin')
def delete_multi_template(tpl_id):
    ok, err = multi_repo_service.delete_template(tpl_id)
    if not ok:
        return error_response(err, 400)
    return success_response(msg='删除成功')


@require_any_permission('page:cicd', 'op:cicd_build')
def item_branches(item_id):
    branches, err = multi_repo_service.list_item_branches(item_id)
    if err:
        return error_response(err, 502)
    return success_response(branches)


@require_permission('op:cicd_build')
def build_item(item_id):
    data = request.json or {}
    env_id = data.get('environment_id')
    if not env_id:
        return error_response('请选择环境', 400)
    from flask import g
    user = getattr(g, 'current_user', None)
    triggered_by = (getattr(user, 'username', '') or 'system') if user else 'system'
    build, err = multi_repo_service.trigger_item_build(
        item_id, env_id, data.get('branch') or 'master', triggered_by,
        maven_settings_id=data.get('maven_settings_id'),
        service_names=data.get('services') or None)
    if err:
        return error_response(err, 400)
    return success_response({'build_id': build.id, 'build_no': build.build_no}, '构建已触发')

@require_permission('op:cicd_build')
def build_items(tpl_id):
    """批量构建：多选时统一使用第一个仓库的分支，单选时使用该仓库分支。"""
    data = request.json or {}
    env_id = data.get('environment_id')
    if not env_id:
        return error_response('请选择环境', 400)
    from flask import g
    user = getattr(g, 'current_user', None)
    triggered_by = (getattr(user, 'username', '') or 'system') if user else 'system'
    result, err = multi_repo_service.trigger_items_build(
        tpl_id, data.get('item_ids') or [], env_id,
        data.get('branch') or 'master', triggered_by,
        maven_settings_id=data.get('maven_settings_id'),
        service_names=data.get('services') or None)
    if err:
        return error_response(err, 400)
    batch, builds = result
    return success_response({
        'batch_id': batch.id,
        'batch_no': batch.batch_no,
        'count': len(builds),
        'builds': [{'build_id': b.id, 'build_no': b.build_no, 'project_type': b.project_type} for b in builds],
    }, f'已触发 {len(builds)} 个仓库构建')

@require_any_permission('page:cicd', 'op:cicd_build')
def get_multi_template_by_project(project_id):
    tpl = multi_repo_service.get_by_project(project_id)
    if not tpl:
        return error_response('该项目未配置多仓库模板', 404)
    return success_response(tpl.to_dict(include_items=True))



@require_any_permission('page:cicd', 'op:cicd_build')
def list_multi_batches():
    project_id = request.args.get('project_id', type=int)
    environment_id = request.args.get('environment_id', type=int)
    q = CicdBuildBatch.query
    if project_id:
        q = q.filter_by(project_id=project_id)
    if environment_id:
        q = q.filter_by(environment_id=environment_id)
    return success_response([b.to_dict(include_builds=False) for b in q.order_by(CicdBuildBatch.id.desc()).limit(100).all()])


@require_any_permission('page:cicd', 'op:cicd_build')
def get_multi_batch(batch_id):
    batch = CicdBuildBatch.query.get(batch_id)
    if not batch:
        return error_response('批次不存在', 404)
    return success_response(multi_repo_service.batch_detail(batch))
