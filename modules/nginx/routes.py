# -*- coding: utf-8 -*-
"""Nginx配置域路由注册"""
from flask import Blueprint

nginx_bp = Blueprint('nginx', __name__)

from modules.nginx.api import list_configs, sync_configs, get_file_content, push_and_reload

nginx_bp.add_url_rule('/list', 'list_configs', list_configs, methods=['GET'])
nginx_bp.add_url_rule('/sync', 'sync_configs', sync_configs, methods=['POST'])
nginx_bp.add_url_rule('/file/<int:file_id>', 'get_file_content', get_file_content, methods=['GET'])
nginx_bp.add_url_rule('/push/<int:file_id>', 'push_and_reload', push_and_reload, methods=['POST'])


def register(app):
    """注册Nginx配置域蓝图"""
    app.register_blueprint(nginx_bp, url_prefix='/api/nginx')
