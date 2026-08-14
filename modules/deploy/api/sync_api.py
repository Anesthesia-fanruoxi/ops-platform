# -*- coding: utf-8 -*-
"""
环境同步接口处理函数 - 目录扫描导入、配置补全
"""
import os
import re
import yaml
import json
import threading
from datetime import datetime
from flask import request, current_app
from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.api.shared import get_output_dir, get_recycle_dir, get_k8s_yaml_remote_dir
from modules.deploy.services.deploy_utils import _deploy_tasks, _tasks_lock, _write_log, _clear_log


# ─── 配置解析工具 ─────────────────────────────────────────

def _get_common_settings():
    """从系统设置读取公共配置"""
    from modules.system.models import Setting
    mapping = {
        'default_publicurl': 'publicurl',
        'default_privateurl': 'privateurl',
        'default_publicbucket': 'publicbucket',
        'default_privatebucket': 'privatebucket',
        'default_ossak': 'ossak',
        'default_osssk': 'osssk',
        'default_encrypted': 'encrypted',
        'default_riskKey': 'riskKey',
        'default_es_pass': 'es_pass',
    }
    result = {}
    for setting_key, config_key in mapping.items():
        s = Setting.query.filter_by(key=setting_key).first()
        result[config_key] = s.value if s else ''
    return result


def _read_yaml_key_fields(item_path):
    """从第一个 deployment YAML 读取关键环境变量（domain, nacos_namespace 等）"""
    dep_dir = os.path.join(item_path, 'deployment')
    if not os.path.isdir(dep_dir):
        return {}
    dep_files = sorted([f for f in os.listdir(dep_dir) if f.endswith(('.yaml', '.yml'))])
    if not dep_files:
        return {}
    try:
        with open(os.path.join(dep_dir, dep_files[0]), 'r', encoding='utf-8') as fp:
            doc = yaml.safe_load(fp)
        containers = doc.get('spec', {}).get('template', {}).get('spec', {}).get('containers', [])
        if not containers:
            return {}
        # 搜索所有容器，找到包含 NACOS_NAMESPACE 的主容器
        env_vars = {}
        target_keys = {'DOMAIN', 'NACOS_NAMESPACE', 'SEATA_NACOS_NAMESPACE'}
        for container in containers:
            for e in container.get('env', []):
                name = e.get('name', '')
                if name in target_keys and 'value' in e:
                    env_vars[name] = e.get('value', '') or ''
        return {
            'domain': env_vars.get('DOMAIN', ''),
            'nacos_namespace': env_vars.get('NACOS_NAMESPACE', ''),
            'seata_nacos_namespace': env_vars.get('SEATA_NACOS_NAMESPACE', ''),
        }
    except Exception:
        return {}


def _parse_deploy_config(item_path, project_name, env_name):
    """从目录解析 deploy_config（不含 nacos_namespace，它存储在独立字段）"""
    deploy_config = {
        'tag': 'latest',
        'domain': '',
        'debug_port': 30000, 'node_port': 30030,
        'jmx_port': 30060, 'middleware_port': 30090,
        'publicurl': '', 'privateurl': '',
        'publicbucket': '', 'privatebucket': '',
        'ossak': '', 'osssk': '',
        'encrypted': '', 'riskKey': '', 'es_pass': '',
        'services': [], 'middleware': [],
    }

    # 1. 从 YAML 读取 domain（直接使用，不做后缀拼接）
    yaml_info = _read_yaml_key_fields(item_path)
    if yaml_info.get('domain'):
        deploy_config['domain'] = yaml_info['domain']

    # 2. 解析每个 service YAML
    svc_dir = os.path.join(item_path, 'service')
    if os.path.isdir(svc_dir):
        svc_files = sorted([f for f in os.listdir(svc_dir) if f.endswith(('.yaml', '.yml'))])
        for i, f in enumerate(svc_files):
            try:
                with open(os.path.join(svc_dir, f), 'r', encoding='utf-8') as fp:
                    doc = yaml.safe_load(fp)
                if not doc or doc.get('kind') != 'Service':
                    continue
                name = doc.get('metadata', {}).get('name', '')
                short = name[len(project_name) + 1:] if name.startswith(project_name + '-') else name
                ports = {p.get('name', ''): p.get('nodePort', 0) for p in doc.get('spec', {}).get('ports', [])}
                deploy_config['services'].append({
                    'name': short,
                    'debug_port': ports.get('debug', 0),
                    'node_port': ports.get('service', 0),
                    'jmx_port': ports.get('jmx', 0),
                })
                if i == 0:
                    deploy_config['debug_port'] = ports.get('debug', 30001) - 1
                    deploy_config['node_port'] = ports.get('service', 30031) - 1
                    deploy_config['jmx_port'] = ports.get('jmx', 30061) - 1
            except Exception:
                pass

    # 3. 列出 middleware
    mw_dir = os.path.join(item_path, 'middleware')
    if os.path.isdir(mw_dir):
        for f in sorted(os.listdir(mw_dir)):
            if f.endswith(('.yaml', '.yml')):
                deploy_config['middleware'].append({'name': f.replace('.yaml', '').replace('.yml', '')})

    return deploy_config


# ─── 同步后台任务 ─────────────────────────────────────────

def _run_sync_task(app, output_dir):
    """后台线程：执行同步并写入日志文件"""
    from core.db import db
    from modules.deploy.models import Environment, Project
    from modules.deploy.services.k8s_service import K8sService

    log_file = os.path.join('logs', 'sync.log')
    _clear_log(log_file)

    def log(level, message, step=None):
        _write_log(log_file, level, message, step)

    with _tasks_lock:
        _deploy_tasks['sync'] = {
            'status': 'running', 'log_file': log_file,
            'started_at': datetime.now().isoformat(),
            'project_name': 'sync', 'env_name': 'sync'
        }

    with app.app_context():
        try:
            # 阶段0: 从K8s Master同步到本地（文件级强一致）
            log('INFO', '从K8s Master同步YAML文件到本地...')
            try:
                k8s = K8sService()
                log('INFO', f'  K8s连接: {k8s.username}@{k8s.host}:{k8s.port}')
                remote_dir = get_k8s_yaml_remote_dir()
                log('INFO', f'  远程目录: {remote_dir}')
                if not k8s.host:
                    log('WARN', '  K8s Master地址未配置，跳过远程同步')
                elif not k8s.password:
                    log('WARN', '  K8s Master SSH密码未配置，跳过远程同步')
                elif k8s.remote_directory_exists(remote_dir):
                    log('INFO', f'  远程目录存在，开始文件级同步...')
                    sync_result = k8s.sync_directory(remote_dir, output_dir, log=lambda lvl, msg: log(lvl, f'  {msg}'))
                    log('OK', f'  同步完成: 新增{len(sync_result["added"])}个, 更新{len(sync_result["updated"])}个, 删除{len(sync_result["deleted"])}个, 跳过{sync_result["unchanged"]}个')
                else:
                    log('WARN', f'  远程目录不存在: {remote_dir}，使用本地文件')
            except Exception as e:
                log('WARN', f'  远程同步失败: {str(e)}，使用本地文件')

            # 阶段1: 扫描目录
            if not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            items = [d for d in os.listdir(output_dir) if os.path.isdir(os.path.join(output_dir, d))]
            total = len(items)
            log('INFO', f'扫描目录: {output_dir}')
            log('INFO', f'发现 {total} 个目录')

            # 读取公共配置（从系统设置）
            common_settings = _get_common_settings()
            log('INFO', f'公共配置已加载: domain={common_settings.get("publicurl", "")}')

            # 读取忽略的项目列表
            from modules.system.models import Setting
            ignored_setting = Setting.query.filter_by(key='ignored_projects').first()
            ignored_projects = set(
                p.strip() for p in (ignored_setting.value or '').split(',') if p.strip()
            )
            if ignored_projects:
                log('INFO', f'忽略的项目: {", ".join(ignored_projects)}')

            imported = []
            removed = []
            updated = []
            field_updated = []  # 字段更新(nacos/domain)
            dir_env_set = set()
            process_count = 0

            # 阶段2: 逐个处理
            for item in items:
                item_path = os.path.join(output_dir, item)
                match = re.match(r'^(.+)-(.+)$', item)
                if not match:
                    continue
                project_name, env_name = match.group(1), match.group(2)
                if project_name == 'recycle':
                    continue
                if project_name in ignored_projects:
                    log('INFO', f'跳过忽略的项目: {project_name} ({item})')
                    continue

                has_deployment = os.path.exists(os.path.join(item_path, 'deployment'))
                if not has_deployment:
                    continue

                process_count += 1
                dir_env_set.add((project_name, env_name))

                log('INFO', f'[{process_count}/{total}] 处理: {item}', step=f'{process_count}/{total}')

                # 查找或创建项目
                project = Project.query.filter_by(name=project_name).first()
                if not project:
                    project = Project(name=project_name, description=f'自动导入: {project_name}')
                    db.session.add(project)
                    db.session.flush()
                    log('INFO', f'  新建项目: {project_name}')

                # 检查环境是否已存在
                existing_env = Environment.query.filter_by(
                    project_id=project.id, name=env_name
                ).first()

                if existing_env:
                    # 已有环境：始终从 YAML 更新 nacos_namespace 和 domain
                    needs_update = False
                    changes = []
                    yaml_info = _read_yaml_key_fields(item_path)

                    # 始终更新 nacos_namespace（独立字段）
                    new_nacos = yaml_info.get('nacos_namespace', '')
                    new_seata = yaml_info.get('seata_nacos_namespace', '')
                    if existing_env.nacos_namespace != new_nacos or existing_env.seata_nacos_namespace != new_seata:
                        existing_env.nacos_namespace = new_nacos
                        existing_env.seata_nacos_namespace = new_seata
                        needs_update = True
                        changes.append(f'nacos={new_nacos}')

                    # 始终从 YAML 更新 domain（直接使用 YAML 值，不做拼接）
                    yaml_domain = yaml_info.get('domain', '')
                    if yaml_domain and existing_env.domain != yaml_domain:
                        changes.append(f'domain: {existing_env.domain}->{yaml_domain}')
                        existing_env.domain = yaml_domain
                        needs_update = True

                    # 补全 deploy_config（如果为空）
                    if not existing_env.deploy_config:
                        deploy_config = _parse_deploy_config(item_path, project_name, env_name)
                        deploy_config.update(common_settings)
                        existing_env.deploy_config = json.dumps(deploy_config, ensure_ascii=False)
                        svc_count = len(deploy_config.get('services', []))
                        mw_count = len(deploy_config.get('middleware', []))
                        changes.append(f'补全deploy_config({svc_count}服务,{mw_count}中间件)')
                        updated.append(f'{project_name}-{env_name}')
                        needs_update = True

                    if needs_update:
                        field_updated.append(f'{project_name}-{env_name}')
                        log('OK', f'  更新: {", ".join(changes)}')
                    else:
                        log('INFO', f'  已存在，无变化')
                    continue

                # 新环境：解析配置
                deploy_config = _parse_deploy_config(item_path, project_name, env_name)
                deploy_config.update(common_settings)
                yaml_info = _read_yaml_key_fields(item_path)
                port_start = deploy_config.get('debug_port', 30000)
                svc_count = len(deploy_config.get('services', []))
                mw_count = len(deploy_config.get('middleware', []))
                nacos_ns = yaml_info.get('nacos_namespace', '')
                log('INFO', f'  解析完成: {svc_count}个服务, {mw_count}个中间件, nacos={nacos_ns}')

                env = Environment(
                    project_id=project.id,
                    name=env_name,
                    domain=yaml_info.get('domain', '') or f'{project_name}{env_name}',
                    port_start=port_start,
                    nacos_namespace=nacos_ns,
                    seata_nacos_namespace=yaml_info.get('seata_nacos_namespace', ''),
                    deploy_config=json.dumps(deploy_config, ensure_ascii=False)
                )
                db.session.add(env)
                imported.append(f'{project_name}-{env_name}')
                log('OK', f'  导入成功: port={port_start}, {svc_count}个服务, {mw_count}个中间件')

            # 阶段3: 反向清理
            log('INFO', '检查并清理无效记录...', step='清理')
            recycle_dir = get_recycle_dir()
            recycle_env_set = set()
            if os.path.isdir(recycle_dir):
                for item in os.listdir(recycle_dir):
                    item_path = os.path.join(recycle_dir, item)
                    if not os.path.isdir(item_path):
                        continue
                    match = re.match(r'^(.+)-(.+)-\d{14}$', item)
                    if match:
                        recycle_env_set.add((match.group(1), match.group(2)))

            active_envs = Environment.query.filter(
                (Environment.is_deleted == False) | (Environment.is_deleted == None)
            ).all()
            for env in active_envs:
                proj_name = env.project.name if env.project else ''
                if proj_name in ignored_projects:
                    continue  # 忽略的项目不参与清理
                key = (proj_name, env.name)
                if key not in dir_env_set:
                    if key in recycle_env_set:
                        env.is_deleted = True
                        env.deleted_at = datetime.now()
                        removed.append(f'{proj_name}-{env.name} (已回收)')
                    else:
                        db.session.delete(env)
                        removed.append(f'{proj_name}-{env.name} (已清除)')

            # 清理已删除记录
            deleted_envs = Environment.query.filter_by(is_deleted=True).all()
            for env in deleted_envs:
                proj_name = env.project.name if env.project else ''
                if proj_name in ignored_projects:
                    continue  # 忽略的项目不参与清理
                key = (proj_name, env.name)
                if key not in recycle_env_set:
                    db.session.delete(env)
                    removed.append(f'{proj_name}-{env.name} (已清除)')

            db.session.commit()

            # 清理空项目
            all_projects = Project.query.all()
            for proj in all_projects:
                if proj.name in ignored_projects:
                    continue  # 忽略的项目不参与清理
                env_count = Environment.query.filter_by(project_id=proj.id).count()
                if env_count == 0:
                    db.session.delete(proj)
                    removed.append(f'项目: {proj.name}')
            db.session.commit()

            if updated:
                log('INFO', f'补全 deploy_config: {len(updated)}个环境')
            if field_updated:
                log('INFO', f'字段更新: {", ".join(field_updated)}')

            # 完成
            elapsed = (datetime.now() - datetime.strptime(
                _deploy_tasks.get('sync', {}).get('started_at', datetime.now().isoformat())[:19],
                '%Y-%m-%dT%H:%M:%S'
            )).total_seconds()
            log('DONE', f'同步完成: 新增{len(imported)}个, 更新{len(field_updated)}个, 补全{len(updated)}个, 清理{len(removed)}个, 耗时{elapsed:.1f}秒')

            with _tasks_lock:
                _deploy_tasks['sync']['status'] = 'completed'

        except Exception as e:
            log('FAILED', f'同步异常终止: {str(e)}')
            import traceback
            log('ERROR', traceback.format_exc())
            with _tasks_lock:
                _deploy_tasks['sync']['status'] = 'failed'


# ─── 同步处理函数 ─────────────────────────────────────────────

@require_permission('op:deploy_project')
def refresh_environments():
    """异步同步：远程下载到本地 → 目录→数据库（新增）+ 数据库→目录（清理）+ 补全 deploy_config"""
    output_dir = get_output_dir()

    with _tasks_lock:
        existing = _deploy_tasks.get('sync')
        if existing and existing.get('status') == 'running':
            return error_response('同步任务正在进行中', 409)

    app = current_app._get_current_object()
    t = threading.Thread(target=_run_sync_task, args=(app, output_dir), daemon=True)
    t.start()

    return success_response({'status': 'running'})
