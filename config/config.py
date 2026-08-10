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
    # 服务启动端口（config.yaml server 段优先）
    SERVER_HOST = _yaml_get('server', 'host', default='0.0.0.0')
    SERVER_PORT = int(_yaml_get('server', 'port', default=8050))

    # MySQL 连接（config.yaml mysql 段优先，其次环境变量）
    MYSQL_HOST = _yaml_get('mysql', 'hostname', default=os.getenv('MYSQL_HOST', '192.168.6.2'))
    MYSQL_PORT = int(_yaml_get('mysql', 'port', default=os.getenv('MYSQL_PORT', '3306')))
    MYSQL_DB = _yaml_get('mysql', 'database', default=os.getenv('MYSQL_DB', 'ops-platform'))
    MYSQL_USER = _yaml_get('mysql', 'username', default=os.getenv('MYSQL_USER', 'root'))
    MYSQL_PASS = _yaml_get('mysql', 'password', default=os.getenv('MYSQL_PASS', 'root'))
    SQLALCHEMY_DATABASE_URI = (
        f'mysql+pymysql://{MYSQL_USER}:{MYSQL_PASS}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4'
    )

    # Redis 配置（config.yaml redis 段优先：认证会话、Agent 心跳、分布式锁、调度概览缓存）
    REDIS_ENABLED = _yaml_get('redis', 'enabled', default=True)
    if isinstance(REDIS_ENABLED, str):
        REDIS_ENABLED = REDIS_ENABLED.lower() in ('1', 'true', 'yes', 'on')
    _REDIS_HOST = _yaml_get('redis', 'hostname', default=os.getenv('REDIS_HOST', '192.168.6.2'))
    _REDIS_PORT = int(_yaml_get('redis', 'port', default=os.getenv('REDIS_PORT', '6380')))
    _REDIS_PASS = _yaml_get('redis', 'password', default=os.getenv('REDIS_PASSWORD', 'redis'))
    _REDIS_DB = int(_yaml_get('redis', 'db', default=os.getenv('REDIS_DB', '0')))
    REDIS_URL = f'redis://:{_REDIS_PASS}@{_REDIS_HOST}:{_REDIS_PORT}/{_REDIS_DB}'
    REDIS_KEY_PREFIX = _yaml_get('redis', 'key_prefix', default=os.getenv('REDIS_KEY_PREFIX', '')) or ''


config = {
    'default': Config,
}
