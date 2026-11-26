# -*- coding: utf-8 -*-
"""多仓库模板模型（独立于单仓流程模板）

一个项目一份多仓库模板，模板下每个仓库一行构建配置，仓库下再挂服务映射。
单仓项目仍走 CicdFlowTemplate，本模块只在多仓库分支/页面使用。
"""
from datetime import datetime

from core.db import db


class CicdMultiTemplate(db.Model):
    __tablename__ = 'cicd_multi_templates'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    name = db.Column(db.String(100), default='')
    description = db.Column(db.String(300), default='')
    enabled = db.Column(db.Boolean, default=True)
    maven_settings_id = db.Column(db.Integer, nullable=True)  # 默认 Maven settings（构建时可覆盖）
    publish_artifacts = db.Column(db.Boolean, default=False)  # 构建成功后自动 deploy 到私仓
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    project = db.relationship('Project', lazy=True,
                              primaryjoin='foreign(CicdMultiTemplate.project_id) == Project.id')

    def items(self):
        return CicdMultiItem.query.filter_by(template_id=self.id) \
            .order_by(CicdMultiItem.sort_no.asc(), CicdMultiItem.id.asc()).all()

    def to_dict(self, include_items=True):
        from modules.cicd.models import MavenSettings
        ms = MavenSettings.query.get(self.maven_settings_id) if self.maven_settings_id else None
        data = {
            'id': self.id,
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else '',
            'name': self.name or '',
            'description': self.description or '',
            'enabled': bool(self.enabled),
            'maven_settings_id': self.maven_settings_id,
            'maven_settings_name': ms.name if ms else '',
            'publish_artifacts': bool(self.publish_artifacts),
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }
        items = self.items() if include_items else []
        data['repo_count'] = len(items) if include_items else CicdMultiItem.query.filter_by(template_id=self.id).count()
        data['service_count'] = sum(item.service_count() for item in items) if include_items else 0
        if include_items:
            data['items'] = [item.to_dict() for item in items]
        else:
            # 列表页只需要服务总数，避免把 items/services 全带出来
            total = 0
            for item in CicdMultiItem.query.filter_by(template_id=self.id).all():
                total += item.service_count()
            data['service_count'] = total
        return data


class CicdMultiItem(db.Model):
    """多仓库模板中的一行：一个 Git 仓库的构建配置"""
    __tablename__ = 'cicd_multi_items'

    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, nullable=False, index=True)
    repo_name = db.Column(db.String(100), nullable=False)
    git_url = db.Column(db.String(300), default='')
    git_credential_id = db.Column(db.Integer, nullable=True)
    language = db.Column(db.String(30), default='')
    git_docker_image = db.Column(db.String(200), default='hub.hzbxhd.com/library/git-clone:1.0')
    build_docker_image = db.Column(db.String(200), default='')
    build_command = db.Column(db.Text, default='')
    dockerfile_template_id = db.Column(db.Integer, nullable=True)
    description = db.Column(db.String(200), default='')
    enabled = db.Column(db.Boolean, default=True)
    sort_no = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('template_id', 'repo_name', name='uq_multi_item_repo'),
    )

    def services(self):
        return CicdMultiService.query.filter_by(item_id=self.id, enabled=True) \
            .order_by(CicdMultiService.sort_no.asc(), CicdMultiService.id.asc()).all()

    def service_count(self):
        return CicdMultiService.query.filter_by(item_id=self.id, enabled=True).count()

    def to_dict(self):
        return {
            'id': self.id,
            'template_id': self.template_id,
            'repo_name': self.repo_name,
            'git_url': self.git_url or '',
            'git_credential_id': self.git_credential_id,
            'language': self.language or '',
            'git_docker_image': self.git_docker_image or 'hub.hzbxhd.com/library/git-clone:1.0',
            'build_docker_image': self.build_docker_image or '',
            'build_command': self.build_command or '',
            'dockerfile_template_id': self.dockerfile_template_id,
            'description': self.description or '',
            'enabled': bool(self.enabled),
            'sort_no': self.sort_no or 0,
            'service_count': self.service_count(),
            'services': [s.to_dict() for s in self.services()],
        }


class CicdMultiService(db.Model):
    """仓库产出的服务（可后补，不阻塞构建）"""
    __tablename__ = 'cicd_multi_services'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, nullable=False, index=True)
    service_name = db.Column(db.String(100), nullable=False)
    artifact_dir = db.Column(db.String(300), default='')  # 相对仓库根目录的产物目录，"." = 仓库根目录
    jar_name = db.Column(db.String(200), default='')
    jvm = db.Column(db.String(10), default='')             # 8 / 17，空则由环境默认
    sort_no = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('item_id', 'service_name', name='uq_multi_service'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'item_id': self.item_id,
            'service_name': self.service_name,
            'artifact_dir': self.artifact_dir or '',
            'jar_name': self.jar_name or '',
            'jvm': self.jvm or '',
            'sort_no': self.sort_no or 0,
            'enabled': bool(self.enabled),
        }


class CicdBuildBatch(db.Model):
    """多仓一次发版的批次记录；child Build 通过 batch_id 归属。

    用户视角一个批次就是一次构建；内部仍保留每个仓库一个 Build，
    便于 Agent 独立执行、重跑和日志 SSE。
    """
    __tablename__ = 'cicd_build_batches'

    id = db.Column(db.Integer, primary_key=True)
    batch_no = db.Column(db.String(50), unique=True, nullable=False, index=True)
    project_id = db.Column(db.Integer, nullable=False, index=True)
    environment_id = db.Column(db.Integer, nullable=True, index=True)
    template_id = db.Column(db.Integer, nullable=True, index=True)
    branch = db.Column(db.String(200), default='master')
    status = db.Column(db.String(20), default='pending')  # pending|running|success|failed|cancelled
    total_services = db.Column(db.Integer, default=0)
    total_builds = db.Column(db.Integer, default=0)
    triggered_by = db.Column(db.String(80), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    project = db.relationship('Project', lazy=True,
                              primaryjoin='foreign(CicdBuildBatch.project_id) == Project.id')
    environment = db.relationship('Environment', lazy=True,
                                  primaryjoin='foreign(CicdBuildBatch.environment_id) == Environment.id')

    def to_dict(self, include_builds=False):
        from modules.cicd.models import Build
        builds = Build.query.filter_by(batch_id=self.id).order_by(Build.id.asc()).all()
        counts = {'success': 0, 'failed': 0, 'running': 0, 'pending': 0, 'cancelled': 0}
        for b in builds:
            counts[b.status] = counts.get(b.status, 0) + 1
        data = {
            'id': self.id,
            'batch_no': self.batch_no,
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else '',
            'environment_id': self.environment_id,
            'environment_name': self.environment.name if self.environment else '',
            'template_id': self.template_id,
            'branch': self.branch or '',
            'status': self.status,
            'total_services': self.total_services or 0,
            'total_builds': self.total_builds or len(builds),
            'triggered_by': self.triggered_by or '',
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'started_at': self.started_at.strftime('%Y-%m-%d %H:%M:%S') if self.started_at else None,
            'finished_at': self.finished_at.strftime('%Y-%m-%d %H:%M:%S') if self.finished_at else None,
            'build_status_counts': counts,
        }
        if include_builds:
            data['builds'] = [b.to_dict() for b in builds]
        return data
