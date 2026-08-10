# -*- coding: utf-8 -*-
"""
共享工具函数（从旧 manage.py 提取）
"""


def get_output_dir():
    """从系统设置获取输出目录"""
    from modules.system.models import Setting
    from flask import current_app
    with current_app.app_context():
        setting = Setting.query.filter_by(key='yaml_output_dir').first()
        return setting.value if setting else './output'


def get_recycle_dir():
    """从系统设置获取回收目录"""
    from modules.system.models import Setting
    from flask import current_app
    with current_app.app_context():
        setting = Setting.query.filter_by(key='yaml_recycle_dir').first()
        return setting.value if setting else './recycle'


def get_k8s_yaml_remote_dir():
    """从系统设置获取K8s远程YAML目录"""
    from modules.system.models import Setting
    from flask import current_app
    with current_app.app_context():
        setting = Setting.query.filter_by(key='k8s_yaml_remote_dir').first()
        return setting.value if setting else '/data/yaml'


def get_k8s_yaml_remote_recycle_dir():
    """从系统设置获取K8s远程YAML回收目录"""
    from modules.system.models import Setting
    from flask import current_app
    with current_app.app_context():
        setting = Setting.query.filter_by(key='k8s_yaml_remote_recycle_dir').first()
        return setting.value if setting else '/data/yaml-recycle'


def get_ignored_projects():
    """从系统设置获取忽略的项目列表"""
    from modules.system.models import Setting
    setting = Setting.query.filter_by(key='ignored_projects').first()
    if not setting or not setting.value:
        return set()
    return set(p.strip() for p in setting.value.split(',') if p.strip())
