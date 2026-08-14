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
from modules.database import routes as database_routes
from modules.cicd import routes as cicd_routes

MODULES = [system_routes, deploy_routes, nginx_routes, database_routes, cicd_routes]


def create_app(config_name='default'):
    """创建Flask应用"""
    app = Flask(__name__)

    @app.after_request
    def _no_cache_html(resp):
        """HTML 页面不缓存：避免浏览器缓存旧页面结构（如新增 JS 引入后仍用旧 HTML 导致组件未定义）"""
        if resp.content_type and resp.content_type.startswith('text/html'):
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            resp.headers['Pragma'] = 'no-cache'
            resp.headers['Expires'] = '0'
        return resp

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

    # 健康检查：请求耗时采样（事件循环/调度延迟维度）
    from modules.system.healthz import register_request_hooks
    register_request_hooks(app)

    # 审计：全局写操作拦截器（自动记录管理操作轨迹）
    from core.audit import register_hooks as register_audit_hooks
    register_audit_hooks(app)

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

    # 固化 Redis 连接配置（后台线程 binlog 监听等无 app context 场景使用）
    from core import redis_client
    redis_client.init_app(app)

    # 注册各业务域蓝图
    for module in MODULES:
        module.register(app)

    # 全局鉴权钩子
    from core.security import init_auth
    init_auth(app)

    # DDL自动同步管理器：按任务配置拉起binlog监听线程（配置变化自动增量对齐）
    from modules.database.ddl_sync import ddl_sync_manager
    ddl_sync_manager.start(app)

    # 页面路由 - 所有页面使用同一个模板，通过Vue Router切换
    @app.route('/')
    @app.route('/<path:path>')
    def index(path=''):
        return render_template('base.html')

    return app


if __name__ == '__main__':
    app = create_app()
    _cfg = config['default']
    # debug=False：禁用 Werkzeug reloader，避免父/子双进程各起一份 DDL 监听线程
    app.run(host=_cfg.SERVER_HOST, port=_cfg.SERVER_PORT, debug=False)
