# -*- coding: utf-8 -*-
"""
配置管理
"""
import os
from pathlib import Path

import yaml


def _load_yaml_config():
    """读取启动配置文件 config/config.yaml；不存在或解析失败直接报错（启动必需）"""
    path = Path(__file__).resolve().parent / 'config.yaml'
    if not path.exists():
        raise RuntimeError(f'缺少启动配置文件: {path}（请创建 config/config.yaml 并填写 MySQL/Redis/服务端口）')
    try:
        with open(path, encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        raise RuntimeError(f'启动配置文件解析失败: {path}（{e}）') from e
    if not isinstance(data, dict):
        raise RuntimeError(f'启动配置文件格式错误（顶层应为映射）: {path}')
    return data


_YAML = _load_yaml_config()


def _yaml_get(*keys, default=None):
    """按路径读取 YAML 配置项；缺失返回 default"""
    node = _YAML
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node if node is not None else default


class Config:
    """基础配置"""
    # 环境变量优先，其次 config.yaml（Docker 部署用环境变量注入连接信息）
    SERVER_HOST = os.getenv('SERVER_HOST') or _yaml_get('server', 'host', default='0.0.0.0')
    SERVER_PORT = int(os.getenv('SERVER_PORT') or _yaml_get('server', 'port', default=8050))

    # MySQL 连接（环境变量优先，其次 config.yaml mysql 段）
    MYSQL_HOST = os.getenv('MYSQL_HOST') or _yaml_get('mysql', 'hostname', default='192.168.6.2')
    MYSQL_PORT = int(os.getenv('MYSQL_PORT') or _yaml_get('mysql', 'port', default='3306'))
    MYSQL_DB = os.getenv('MYSQL_DB') or _yaml_get('mysql', 'database', default='ops-platform')
    MYSQL_USER = os.getenv('MYSQL_USER') or _yaml_get('mysql', 'username', default='root')
    MYSQL_PASS = os.getenv('MYSQL_PASS') or _yaml_get('mysql', 'password', default='root')
    SQLALCHEMY_DATABASE_URI = (
        f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4'
    )
    # SQLAlchemy 引擎连接池配置（SSE 长连接频繁查 DB，容量需与 gunicorn threads 匹配）
    # pool_size=10：基础连接数；max_overflow=20：溢出允许，合计 30
    # 避免 gunicorn threads 增加到 48 后 DB 连接等待成为新瓶颈
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'max_overflow': 20,
        'pool_pre_ping': True,  # 复用前验证连接可用（防僵尸连接）
        'pool_recycle': 3600,   # 1 小时回收一次连接
    }

    # Redis 配置（环境变量优先，其次 config.yaml redis 段：认证会话、Agent 心跳、分布式锁、调度概览缓存）
    REDIS_ENABLED = os.getenv('REDIS_ENABLED') if os.getenv('REDIS_ENABLED') is not None \
        else _yaml_get('redis', 'enabled', default=True)
    if isinstance(REDIS_ENABLED, str):
        REDIS_ENABLED = REDIS_ENABLED.lower() in ('1', 'true', 'yes', 'on')
    _REDIS_HOST = os.getenv('REDIS_HOST') or _yaml_get('redis', 'hostname', default='192.168.6.2')
    _REDIS_PORT = int(os.getenv('REDIS_PORT') or _yaml_get('redis', 'port', default='6380'))
    _REDIS_PASS = os.getenv('REDIS_PASSWORD') or _yaml_get('redis', 'password', default='redis')
    _REDIS_DB = int(os.getenv('REDIS_DB') or _yaml_get('redis', 'db', default='0'))
    REDIS_URL = f'redis://:{_REDIS_PASS}@{_REDIS_HOST}:{_REDIS_PORT}/{_REDIS_DB}'
    REDIS_KEY_PREFIX = os.getenv('REDIS_KEY_PREFIX') or _yaml_get('redis', 'key_prefix', default='') or ''


config = {
    'default': Config,
}
