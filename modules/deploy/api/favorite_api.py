# -*- coding: utf-8 -*-
"""
环境收藏接口：按当前用户（g.current_user）隔离的「项目+环境」收藏

- GET    /api/deploy/service-info/favorites          列表（按创建时间升序）
- POST   /api/deploy/service-info/favorites          新增（body: project_id, env_id）
- DELETE /api/deploy/service-info/favorites/<id>     删除（仅能删自己的收藏）
"""
from flask import g, request

from core.db import db
from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.models import Project, Environment, DeployEnvFavorite


@require_permission('page:service_info')
def list_favorites():
    """当前用户的全部环境收藏（按自定义排序号，其次创建时间）"""
    items = DeployEnvFavorite.query.filter_by(user_id=g.current_user.id) \
        .order_by(DeployEnvFavorite.sort_no.asc(), DeployEnvFavorite.created_at.asc()).all()
    return success_response([f.to_dict() for f in items])


@require_permission('page:service_info')
def add_favorite():
    """新增收藏：服务端回查 project/env 补全名称并校验存在性，唯一约束冲突幂等返回已存在项"""
    data = request.get_json(force=True, silent=True) or {}
    project_id = data.get('project_id')
    env_id = data.get('env_id')
    if not project_id or not env_id:
        return error_response('缺少 project_id / env_id', 400)

    project = Project.query.get(project_id)
    env = Environment.query.get(env_id)
    if not project or not env or env.project_id != project.id:
        return error_response('项目或环境不存在', 404)

    existing = DeployEnvFavorite.query.filter_by(
        user_id=g.current_user.id, project_id=project.id, env_id=env.id).first()
    if existing:
        return success_response(existing.to_dict(), '已收藏')

    try:
        # 排序号接在当前用户已有收藏之后，新增项排在末尾
        max_row = DeployEnvFavorite.query.filter_by(user_id=g.current_user.id) \
            .order_by(DeployEnvFavorite.sort_no.desc()).first()
        fav = DeployEnvFavorite(
            user_id=g.current_user.id,
            project_id=project.id,
            project_name=project.name,
            env_id=env.id,
            env_name=env.name,
            sort_no=(max_row.sort_no or 0) + 1 if max_row else 1,
        )
        db.session.add(fav)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return error_response(f'收藏保存失败: {str(e)}', 500)
    return success_response(fav.to_dict(), '已收藏')


@require_permission('page:service_info')
def sort_favorites():
    """拖拽自定义排序持久化：body {order: [id,...]}，按数组顺序写 sort_no=0..n（仅限本人收藏）"""
    data = request.get_json(force=True, silent=True) or {}
    order = data.get('order') or []
    if not order:
        return error_response('缺少 order 列表', 400)
    items = DeployEnvFavorite.query.filter_by(user_id=g.current_user.id).all()
    by_id = {f.id: f for f in items}
    try:
        for idx, fid in enumerate(order):
            if fid in by_id:
                by_id[fid].sort_no = idx
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return error_response(f'排序保存失败: {str(e)}', 500)
    return success_response({'count': len(order)})


@require_permission('page:service_info')
def delete_favorite(fid):
    """删除收藏：强制按当前用户过滤，越权/不存在返回 404"""
    fav = DeployEnvFavorite.query.filter_by(id=fid, user_id=g.current_user.id).first()
    if not fav:
        return error_response('收藏不存在或无权限', 404)
    try:
        db.session.delete(fav)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return error_response(f'取消收藏失败: {str(e)}', 500)
    return success_response(None, '已取消收藏')
