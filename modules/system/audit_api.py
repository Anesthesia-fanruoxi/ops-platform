# -*- coding: utf-8 -*-
"""审计日志查询 API（page:audit 权限）"""
from datetime import datetime, timedelta

from flask import request

from core.response import success_response, error_response
from core.security import require_permission
from modules.system.models import AuditLog


@require_permission('page:audit')
def list_audit_logs():
    """审计日志列表（分页 + 多条件筛选）
    参数: page/page_size/user/module/action/result/start_time/end_time
    """
    page = request.args.get('page', 1, type=int)
    page_size = min(request.args.get('page_size', 20, type=int), 100)
    q = AuditLog.query

    username = (request.args.get('username') or '').strip()
    module = (request.args.get('module') or '').strip()
    action = (request.args.get('action') or '').strip()
    result = (request.args.get('result') or '').strip()
    start = (request.args.get('start_time') or '').strip()
    end = (request.args.get('end_time') or '').strip()

    if username:
        q = q.filter(AuditLog.username.like(f'%{username}%'))
    if module:
        q = q.filter(AuditLog.module == module)
    if action:
        q = q.filter(AuditLog.action.like(f'%{action}%'))
    if result:
        q = q.filter(AuditLog.result == result)
    if start:
        try:
            q = q.filter(AuditLog.created_at >= datetime.strptime(start, '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            pass
    if end:
        try:
            q = q.filter(AuditLog.created_at <= datetime.strptime(end, '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            pass

    total = q.count()
    items = q.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return success_response({
        'list': [r.to_dict() for r in items],
        'total': total,
        'page': page,
        'page_size': page_size,
    })


@require_permission('page:audit')
def audit_modules():
    """审计模块/动作/结果枚举（筛选下拉用）"""
    from core.db import db
    from sqlalchemy import text
    modules = [r[0] for r in db.session.execute(text('SELECT DISTINCT module FROM audit_logs ORDER BY module')).fetchall()]
    results = [r[0] for r in db.session.execute(text('SELECT DISTINCT result FROM audit_logs ORDER BY result')).fetchall()]
    return success_response({'modules': modules, 'results': results})
