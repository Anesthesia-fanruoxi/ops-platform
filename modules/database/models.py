# -*- coding: utf-8 -*-
"""
数据库工具域模型：CustomDatasource（自定义数据源）/ DdlSyncTask、DdlSyncLog（DDL 自动同步）
"""
import json
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


class DdlSyncTask(db.Model):
    """DDL 自动同步任务：binlog 监听勾选的数据源，任一源 DDL 变更分发到其他源执行

    - sources：勾选的数据源 instance_id 列表（兼容自动发现数字 id 与 custom-{id}）
    - ignored：勾选但标记「忽略同步」的子集（只发不收：不接收其他源变更，自身变更仍分发）
    - positions：各源 binlog 位点 {'instance_id': {'file':..., 'pos':...} 或 {'gtid':...}}
    """
    __tablename__ = 'ddl_sync_tasks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)          # 任务名
    project = db.Column(db.String(100), default='')           # 所属项目
    database = db.Column(db.String(100), nullable=False)      # 统一库名（各源同步同名库）
    sources = db.Column(db.Text, default='[]')                # JSON 数组：instance_id 列表
    ignored = db.Column(db.Text, default='[]')                # JSON 数组：忽略同步的 instance_id 子集
    positions = db.Column(db.Text, default='{}')              # JSON：各源 binlog 位点
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def _json(self, field, default):
        try:
            v = json.loads(field) if field else default
            return v if isinstance(v, type(default)) else default
        except (json.JSONDecodeError, TypeError):
            return default

    def source_list(self):
        return self._json(self.sources, [])

    def ignored_list(self):
        return self._json(self.ignored, [])

    def position_map(self):
        return self._json(self.positions, {})

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'project': self.project,
            'database': self.database,
            'sources': self.source_list(),
            'ignored': self.ignored_list(),
            'enabled': self.enabled,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
        }


class DdlSyncLog(db.Model):
    """DDL 同步日志：每条 DDL 在每个目标的执行结果（DROP 提示类记录 target_id 为空）"""
    __tablename__ = 'ddl_sync_logs'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, nullable=False, index=True)
    source_id = db.Column(db.String(64), default='')          # 变更源 instance_id
    target_id = db.Column(db.String(64), default='')          # 兼容保留（不再使用，见 targets）
    targets = db.Column(db.Text, default='')                  # JSON: [{id, name, status, error}] 每个目标数据源的执行结果
    schema_name = db.Column(db.String(100), default='')
    ddl_type = db.Column(db.String(32), default='')           # CREATE/ALTER/DROP/RENAME 等
    sql_text = db.Column(db.Text, default='')                 # 截断 4KB
    status = db.Column(db.String(16), default='')             # ok/failed/skipped
    error = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)

    def to_dict(self):
        import json
        try:
            targets = json.loads(self.targets or '[]')
        except Exception:
            targets = []
        return {
            'id': self.id,
            'task_id': self.task_id,
            'source_id': self.source_id,
            'target_id': self.target_id,
            'targets': targets,
            'schema_name': self.schema_name,
            'ddl_type': self.ddl_type,
            'sql_text': self.sql_text,
            'status': self.status,
            'error': self.error,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
        }
