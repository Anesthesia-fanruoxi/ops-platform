# -*- coding: utf-8 -*-
"""首页（Dashboard）概况统计接口：登录即可见，轻量聚合展示平台整体状态"""
from datetime import datetime, timedelta

from core.response import success_response


def dashboard_stats():
    """平台概况统计：项目/环境/用户/认证中心用户/构建/Agent/模板/数据源/近7天审计 + 最近5条构建"""
    from modules.system.models import AuditLog
    from modules.deploy.models import Project, Environment
    from modules.cicd.models import Build, BuildAgent, CicdFlowTemplate
    from modules.database.models import CustomDatasource

    recent = Build.query.order_by(Build.id.desc()).limit(5).all()
    _pnames = {p.id: p.name for p in Project.query.all()}
    _enames = {e.id: e.name for e in Environment.query.all()}
    recent_builds = []
    for b in recent:
        recent_builds.append({
            'build_no': getattr(b, 'build_no', '') or '',
            'project_name': _pnames.get(b.project_id, '') or '',
            'environment_name': _enames.get(b.environment_id, '') or '',
            'branch': getattr(b, 'branch', '') or '',
            'project_type': getattr(b, 'project_type', '') or '',
            'status': getattr(b, 'status', '') or '',
            'created_at': b.created_at.strftime('%m-%d %H:%M') if getattr(b, 'created_at', None) else '',
        })

    return success_response({
        'projects': Project.query.count(),
        'environments': Environment.query.count(),
        'builds': Build.query.count(),
        'agents': BuildAgent.query.count(),
        'templates': CicdFlowTemplate.query.count(),
        'datasources': CustomDatasource.query.count(),
        'audit_7d': AuditLog.query.filter(
            AuditLog.created_at >= datetime.utcnow() - timedelta(days=7)).count(),
        'recent_builds': recent_builds,
    })
