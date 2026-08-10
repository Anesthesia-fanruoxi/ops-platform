# -*- coding: utf-8 -*-
"""
运维平台 - Flask主入口
"""
from flask import Flask, render_template, url_for
from config.config import config

# 业务域模块（每个模块的 routes.py 暴露 register(app)）
from modules.system import routes as system_routes
from modules.deploy import routes as deploy_routes
from modules.nginx import routes as nginx_routes
from modules.collation import routes as collation_routes
from modules.cicd import routes as cicd_routes

MODULES = [system_routes, deploy_routes, nginx_routes, collation_routes, cicd_routes]


def create_app(config_name='default'):
    """创建Flask应用"""
    app = Flask(__name__)

    # 加载配置
    app.config.from_object(config[config_name])
    app.json.ensure_ascii = False

    @app.template_global('static_asset')
    def static_asset(filename):
        """静态资源自动版本号：基于文件修改时间戳，改文件后浏览器自动拉新缓存"""
        import os
        path = os.path.join(app.static_folder or 'static', filename.replace('/', os.sep))
        try:
            v = int(os.path.getmtime(path))
        except OSError:
            v = 0
        return url_for('static', filename=filename) + f'?v={v}'

    # 数据库连接已在 config.py 中按 config/config.yaml 装配（MySQL InnoDB 行级锁，
    # 避免心跳/SSE 写事务互相阻塞）
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 10,
        'max_overflow': 20,
        'pool_recycle': 3600,
        'pool_pre_ping': True,  # 防 MySQL wait_timeout 断连
    }

    # 初始化数据库
    from core.bootstrap import init_db
    init_db(app)

    # 注册各业务域蓝图
    for module in MODULES:
        module.register(app)

    # 全局鉴权钩子
    from core.security import init_auth
    init_auth(app)

    # 页面路由 - 所有页面使用同一个模板，通过Vue Router切换
    @app.route('/')
    @app.route('/<path:path>')
    def index(path=''):
        return render_template('base.html')

    return app


if __name__ == '__main__':
    app = create_app()
    _cfg = config['default']
    app.run(host=_cfg.SERVER_HOST, port=_cfg.SERVER_PORT, debug=True)
