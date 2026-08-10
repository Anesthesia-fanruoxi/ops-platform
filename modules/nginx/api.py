# -*- coding: utf-8 -*-
"""
Nginx配置文件管理接口处理函数 - 同步/查询/查看
"""
import os
import hashlib
import threading
from datetime import datetime
from flask import request
from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.services.deploy_utils import _deploy_tasks, _tasks_lock, _write_log, _clear_log


def _get_nginx_settings():
    """从系统设置读取Nginx配置"""
    from modules.system.models import Setting

    def _get(key, default):
        s = Setting.query.filter_by(key=key).first()
        return s.value if s and s.value else default

    return {
        'server': _get('nginx_server', ''),
        'port': int(_get('nginx_ssh_port', '22')),
        'user': _get('nginx_ssh_user', 'root'),
        'password': _get('nginx_ssh_pass', ''),
        'remote_dir': _get('nginx_remote_dir', '/etc/nginx/conf.d'),
        'local_dir': _get('nginx_local_dir', './nginx_configs'),
    }


def _file_md5(file_path):
    h = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


# ─── 同步后台任务 ─────────────────────────────────────────

def _run_nginx_sync_task(app, config):
    """后台线程：执行Nginx配置文件同步"""
    from modules.nginx.models import NginxConfig
    from core.db import db
    from modules.nginx.service import NginxService

    log_file = os.path.join('logs', 'nginx-sync.log')
    _clear_log(log_file)

    def log(level, message, step=None):
        _write_log(log_file, level, message, step)

    with _tasks_lock:
        _deploy_tasks['nginx-sync'] = {
            'status': 'running', 'log_file': log_file,
            'started_at': datetime.now().isoformat(),
            'project_name': 'nginx', 'env_name': 'sync'
        }

    with app.app_context():
        try:
            # 阶段1: 连接Nginx服务器
            log('INFO', '连接Nginx服务器...')
            nginx = NginxService(
                host=config['server'],
                port=config['port'],
                username=config['user'],
                password=config['password']
            )
            log('INFO', f'  服务器: {config["user"]}@{config["server"]}:{config["port"]}')

            remote_dir = config['remote_dir']
            local_dir = config['local_dir']
            log('INFO', f'  远程目录: {remote_dir}')
            log('INFO', f'  本地目录: {local_dir}')

            if not nginx.host:
                log('ERROR', 'Nginx服务器地址未配置')
                with _tasks_lock:
                    _deploy_tasks['nginx-sync']['status'] = 'failed'
                return

            if not nginx.remote_directory_exists(remote_dir):
                log('ERROR', f'远程目录不存在: {remote_dir}')
                with _tasks_lock:
                    _deploy_tasks['nginx-sync']['status'] = 'failed'
                return

            # 阶段2: 文件级同步（远程为主、本地为辅）
            log('INFO', '开始文件级同步...')
            sync_result = nginx.sync_directory(
                remote_dir, local_dir,
                log=lambda lvl, msg: log(lvl, f'  {msg}')
            )

            added = sync_result['added']
            updated = sync_result['updated']
            deleted = sync_result['deleted']
            unchanged = sync_result['unchanged']

            # 阶段3: 更新数据库（数据库纯查询用途）
            log('INFO', '更新数据库...')
            now = datetime.now()

            # 扫描本地目录，更新DB记录
            local_conf_files = []
            if os.path.isdir(local_dir):
                local_conf_files = [f for f in os.listdir(local_dir) if f.endswith('.conf')]

            # 建立DB映射
            db_records = {r.file_name: r for r in NginxConfig.query.all()}
            db_file_set = set(db_records.keys())
            local_file_set = set(local_conf_files)

            # 新增/更新
            db_changed = 0
            for file_name in local_conf_files:
                file_path = os.path.join(local_dir, file_name)
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    md5 = _file_md5(file_path)
                except Exception:
                    content = ''
                    md5 = ''

                if file_name in db_records:
                    record = db_records[file_name]
                    if record.md5 != md5:
                        record.content = content
                        record.md5 = md5
                        record.synced_at = now
                        db_changed += 1
                else:
                    record = NginxConfig(
                        file_name=file_name,
                        content=content,
                        md5=md5,
                        synced_at=now
                    )
                    db.session.add(record)
                    db_changed += 1

            # 删除DB中远程已不存在的记录
            db_deleted = 0
            for file_name in db_file_set - local_file_set:
                db.session.delete(db_records[file_name])
                db_deleted += 1

            db.session.commit()
            log('INFO', f'  数据库更新: {db_changed}条变更, {db_deleted}条删除')

            # 完成
            elapsed = (datetime.now() - datetime.strptime(
                _deploy_tasks.get('nginx-sync', {}).get('started_at', datetime.now().isoformat())[:19],
                '%Y-%m-%dT%H:%M:%S'
            )).total_seconds()
            log('DONE', f'同步完成: 新增{len(added)}个, 更新{len(updated)}个, 删除{len(deleted)}个, 跳过{unchanged}个, 耗时{elapsed:.1f}秒')

            with _tasks_lock:
                _deploy_tasks['nginx-sync']['status'] = 'completed'

        except Exception as e:
            log('FAILED', f'同步异常终止: {str(e)}')
            import traceback
            log('ERROR', traceback.format_exc())
            with _tasks_lock:
                _deploy_tasks['nginx-sync']['status'] = 'failed'


# ─── 处理函数 ─────────────────────────────────────────────────

@require_permission('page:nginx')
def list_configs():
    """查询所有已同步的配置文件列表"""
    from modules.nginx.models import NginxConfig
    configs = NginxConfig.query.order_by(NginxConfig.file_name).all()
    return success_response([c.to_dict() for c in configs])


@require_permission('op:nginx_push')
def sync_configs():
    """触发Nginx配置文件同步"""
    config = _get_nginx_settings()

    if not config['server']:
        return error_response('Nginx服务器地址未配置，请先在系统设置中填写')

    with _tasks_lock:
        existing = _deploy_tasks.get('nginx-sync')
        if existing and existing.get('status') == 'running':
            return error_response('同步任务正在进行中', 409)

    app = request.app if hasattr(request, 'app') else None
    if not app:
        from flask import current_app
        app = current_app._get_current_object()

    t = threading.Thread(target=_run_nginx_sync_task, args=(app, config), daemon=True)
    t.start()

    return success_response({'status': 'running'})


@require_permission('page:nginx')
def get_file_content(file_id):
    """查看单个配置文件内容"""
    from modules.nginx.models import NginxConfig
    config = NginxConfig.query.get(file_id)
    if not config:
        return error_response('文件不存在', 404)
    return success_response({
        'id': config.id,
        'file_name': config.file_name,
        'content': config.content,
        'md5': config.md5,
        'synced_at': config.synced_at.strftime('%Y-%m-%d %H:%M:%S') if config.synced_at else None
    })


@require_permission('op:nginx_push')
def push_and_reload(file_id):
    """将编辑后的配置文件推送到Nginx服务器并 reload"""
    from modules.nginx.models import NginxConfig
    from core.db import db
    from modules.nginx.service import NginxService

    config = NginxConfig.query.get(file_id)
    if not config:
        return error_response('文件不存在', 404)

    data = request.get_json(silent=True) or {}
    content = data.get('content')
    if content is None:
        return error_response('缺少 content 参数')

    settings = _get_nginx_settings()
    if not settings['server']:
        return error_response('Nginx服务器地址未配置')

    remote_file = f"{settings['remote_dir']}/{config.file_name}"

    try:
        nginx = NginxService(
            host=settings['server'],
            port=settings['port'],
            username=settings['user'],
            password=settings['password']
        )

        # 1. 推送文件到远程
        nginx.push_config(content, remote_file)

        # 2. 测试配置 + reload
        ok, msg = nginx.reload_nginx()
        if not ok:
            return error_response(msg)

        # 3. 更新本地文件和数据库
        local_file = os.path.join(settings['local_dir'], config.file_name)
        os.makedirs(os.path.dirname(local_file), exist_ok=True)
        with open(local_file, 'w', encoding='utf-8') as f:
            f.write(content)

        # 计算新 MD5
        import hashlib as _hashlib
        h = _hashlib.md5()
        h.update(content.encode('utf-8'))
        new_md5 = h.hexdigest()

        config.content = content
        config.md5 = new_md5
        config.synced_at = datetime.now()
        db.session.commit()

        return success_response({
            'id': config.id,
            'file_name': config.file_name,
            'md5': new_md5,
            'synced_at': config.synced_at.strftime('%Y-%m-%d %H:%M:%S'),
            'message': msg
        })

    except Exception as e:
        return error_response(f'推送失败: {str(e)}')
