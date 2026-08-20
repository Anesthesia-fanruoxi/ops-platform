# -*- coding: utf-8 -*-
"""
部署环境域模型：Project / Environment
"""
import json
from datetime import datetime

from core.db import db


class Project(db.Model):
    """项目表"""
    __tablename__ = 'projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class Environment(db.Model):
    """环境表（关联项目，项目+环境名唯一）"""
    __tablename__ = 'environments'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    domain = db.Column(db.String(100), default='')
    port_start = db.Column(db.Integer, default=30000)
    nacos_namespace = db.Column(db.String(200), default='')  # Nacos命名空间（独立字段，可手动/自动更新）
    seata_nacos_namespace = db.Column(db.String(200), default='')  # Seata Nacos命名空间
    is_deleted = db.Column(db.Boolean, default=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    recycle_info = db.Column(db.Text, nullable=True)  # JSON: 回收路径信息
    deploy_config = db.Column(db.Text, nullable=True)  # JSON: 部署参数
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联项目（DB 层无外键，ORM 显式 primaryjoin）
    project = db.relationship('Project', backref=db.backref('environments', lazy=True),
                              primaryjoin='foreign(Environment.project_id) == Project.id')

    # 项目+环境名唯一约束
    __table_args__ = (
        db.UniqueConstraint('project_id', 'name', name='uq_project_env'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'project_name': self.project.name if self.project else '',
            'name': self.name,
            'domain': self.domain,
            'port_start': self.port_start,
            'nacos_namespace': self.nacos_namespace or '',
            'seata_nacos_namespace': self.seata_nacos_namespace or '',
            'is_deleted': self.is_deleted,
            'deleted_at': self.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if self.deleted_at else None,
            'recycle_info': json.loads(self.recycle_info) if self.recycle_info else None,
            'deploy_config': json.loads(self.deploy_config) if self.deploy_config else None,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


class DeployEnvFavorite(db.Model):
    """用户环境收藏（项目+环境二元组，按用户隔离）"""
    __tablename__ = 'deploy_env_favorites'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    project_id = db.Column(db.Integer, nullable=False)
    project_name = db.Column(db.String(50), default='')
    env_id = db.Column(db.Integer, nullable=False)
    env_name = db.Column(db.String(50), default='')
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'project_id', 'env_id', name='uq_user_proj_env'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'project_name': self.project_name,
            'env_id': self.env_id,
            'env_name': self.env_name,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
