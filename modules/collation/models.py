# -*- coding: utf-8 -*-
"""
排序修正域模型：CustomDatasource（自定义数据源）
"""
from datetime import datetime

from core.db import db


class CustomDatasource(db.Model):
    """自定义 MySQL 数据源（用户手动录入）"""
    __tablename__ = 'collation_datasources'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)          # 数据源名称
    host = db.Column(db.String(200), nullable=False)          # 主机地址
    port = db.Column(db.Integer, nullable=False, default=3306)  # 端口
    user = db.Column(db.String(100), nullable=False, default='root')  # 用户名
    password = db.Column(db.String(200), default='')          # 密码
    project = db.Column(db.String(100), default='')           # 所属项目（分组用）
    env = db.Column(db.String(100), default='')               # 环境名称
    description = db.Column(db.String(500), default='')       # 备注
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self, include_password=False):
        data = {
            'id': self.id,
            'name': self.name,
            'host': self.host,
            'port': self.port,
            'user': self.user,
            'project': self.project,
            'env': self.env,
            'description': self.description,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }
        if include_password:
            data['password'] = self.password
        return data
