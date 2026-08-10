# -*- coding: utf-8 -*-
"""
Nginx域模型：NginxConfig
"""
from datetime import datetime

from core.db import db


class NginxConfig(db.Model):
    """Nginx配置文件表"""
    __tablename__ = 'nginx_configs'

    id = db.Column(db.Integer, primary_key=True)
    file_name = db.Column(db.String(200), unique=True, nullable=False)
    content = db.Column(db.Text, default='')
    md5 = db.Column(db.String(32), default='')
    synced_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'file_name': self.file_name,
            'md5': self.md5,
            'synced_at': self.synced_at.strftime('%Y-%m-%d %H:%M:%S') if self.synced_at else None
        }
