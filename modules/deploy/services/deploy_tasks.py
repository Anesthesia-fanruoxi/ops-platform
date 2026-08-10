# -*- coding: utf-8 -*-
"""
部署任务执行逻辑 - 后台线程任务
"""
import os
import json
import time
import shutil
from datetime import datetime
from flask import current_app
from core.db import db
from modules.deploy.models import Project, Environment
from modules.system.models import Setting
from modules.deploy.services.deploy_utils import _deploy_tasks, _tasks_lock, _get_log_path, _write_log


# ─── Harbor 项目创建步骤 ─────────────────────────────────

def _create_harbor_project_step(project_name, env_name, log=None):
    """
    部署步骤：创建Harbor项目并配置清理策略
    """
    from modules.deploy.api.harbor_api import get_harbor_client

    project_full_name = f"{project_name}-{env_name}"
    if log:
        log('INFO', f'准备创建Harbor项目: {project_full_name}')

    try:
        harbor = get_harbor_client()
        existing = harbor.get_project(project_full_name)
        if existing:
            if log:
                log('INFO', f'Harbor项目已存在，跳过创建: {project_full_name}')
            return {'status': 'already_exists', 'project_name': project_full_name}

        result = harbor.create_project(
            project_name=project_full_name,
            public=True,
            metadata={'auto_scan': 'true'}
        )

        if not result['success']:
            msg = result.get('message', 'unknown error')
            if log:
                log('WARN', f'Harbor项目创建失败: {msg}')
            return {'status': 'failed', 'project_name': project_full_name, 'error': msg}

        if log:
            log('INFO', f'Harbor项目创建成功: {project_full_name}')

        time.sleep(2)

        proj_info = harbor.get_project(project_full_name)
        project_id = proj_info.get('project_id') if proj_info else None
        keep_versions = 3
        cron = '0 0 * * * *'
        retention_ref = project_id if project_id else project_full_name
        retention_result = harbor.create_retention_policy(
            project_name_or_id=retention_ref,
            keep_recent=keep_versions,
            cron=cron
        )
        if retention_result['success']:
            if log:
                log('INFO', f'Harbor保留策略创建成功: 保留最近{keep_versions}个版本, 定时{cron}')
        else:
            if log:
                log('WARN', f'Harbor保留策略创建失败: {retention_result.get("status_code")} {retention_result.get("message")}')

        return {
            'status': 'created',
            'project_name': project_full_name,
            'cleanup': {'keep_versions': keep_versions, 'cron': cron}
        }

    except Exception as e:
        if log:
            log('ERROR', f'Harbor项目创建异常: {str(e)}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'project_name': project_full_name, 'error': str(e)}


# ─── 回收任务 ─────────────────────────────────────────────

def _run_recycle_task(app, task_key, env_id):
    """后台线程：执行环境回收并写入日志"""
    with app.app_context():
        from modules.deploy.services.nfs_service import NFSService
        from modules.deploy.services.k8s_service import K8sService
        from modules.deploy.api.shared import get_k8s_yaml_remote_dir, get_k8s_yaml_remote_recycle_dir
        from modules.deploy.api.harbor_api import get_harbor_client
        from datetime import datetime as dt

        env = Environment.query.get(env_id)
        if not env:
            return
        project = env.project
        if not project:
            return

        project_name = project.name
        env_name = env.name
        env_full = f"{project_name}-{env_name}"
        log_file = _get_log_path(project_name, env_name, 'recycle')

        def log(level, message, step=None):
            _write_log(log_file, level, message, step)

        with _tasks_lock:
            _deploy_tasks[task_key] = {
                'status': 'running', 'log_file': log_file,
                'started_at': dt.now().isoformat(),
                'project_name': project_name, 'env_name': env_name
            }

        timestamp = dt.now().strftime('%Y%m%d%H%M%S')
        recycle_info = {}
        success_count = 0
        fail_count = 0
        total_steps = 7

        try:
            # 步骤1: K8s资源清理（mysql缩容保留PVC，其他中间件删除，服务删除）
            log('INFO', 'K8s资源清理...', step=f'步骤1/{total_steps}')
            ns_middleware = f"{env_full}-middleware"
            ns_service = f"{env_full}-service"
            log('INFO', f'  中间件Namespace: {ns_middleware}')
            log('INFO', f'  服务Namespace: {ns_service}')
            try:
                k8s = K8sService()
                import time
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{env_full}"

                # 1. MySQL StatefulSet 缩容（保留PVC数据）
                log('INFO', '  [MySQL] 缩容到0副本（保留PVC数据）...')
                r = k8s.exec_command(f'kubectl get statefulset -n {ns_middleware} -o name')
                if r['stdout']:
                    for res_name in r['stdout'].split('\n'):
                        res_name = res_name.strip()
                        if res_name and 'mysql' in res_name.lower() and 'nfs' not in res_name.lower():
                            r2 = k8s.exec_command(f'kubectl scale {res_name} --replicas=0 -n {ns_middleware}')
                            if r2['exit_code'] == 0:
                                log('OK', f'  已缩容: {res_name} -> 0（PVC保留）')
                            else:
                                log('WARN', f'  缩容失败: {res_name} - {r2["stderr"]}')

                # 2. 删除中间件YAML（跳过mysql.yaml，其他中间件通过delete -f删除）
                log('INFO', '  [中间件] 删除YAML资源（跳过mysql）...')
                r = k8s.exec_command(f'ls {remote_dir}/middleware/ 2>/dev/null')
                if r['stdout']:
                    for yaml_file in r['stdout'].split('\n'):
                        yaml_file = yaml_file.strip()
                        if yaml_file.endswith('.yaml') and yaml_file != 'mysql.yaml' and yaml_file != 'public-config.yaml':
                            yaml_path = f"{remote_dir}/middleware/{yaml_file}"
                            r2 = k8s.exec_command(f'kubectl delete -f {yaml_path} --ignore-not-found')
                            if r2['exit_code'] == 0:
                                log('OK', f'  已删除: {yaml_file}')
                            else:
                                log('WARN', f'  删除失败: {yaml_file} - {r2["stderr"]}')

                # 3. 删除服务YAML
                log('INFO', f'  [服务] 删除YAML资源...')
                for sub_dir in ['deployment', 'service']:
                    r = k8s.exec_command(f'ls {remote_dir}/{sub_dir}/ 2>/dev/null')
                    if r['stdout']:
                        for yaml_file in r['stdout'].split('\n'):
                            yaml_file = yaml_file.strip()
                            if yaml_file.endswith('.yaml'):
                                yaml_path = f"{remote_dir}/{sub_dir}/{yaml_file}"
                                r2 = k8s.exec_command(f'kubectl delete -f {yaml_path} --ignore-not-found')
                                if r2['exit_code'] == 0:
                                    log('OK', f'  已删除: {sub_dir}/{yaml_file}')
                                else:
                                    log('WARN', f'  删除失败: {sub_dir}/{yaml_file} - {r2["stderr"]}')

                # 4. 等待Pod终止（30秒后强制删除）
                log('INFO', '  等待Pod终止...')
                force_deleted = False
                for attempt in range(6):
                    time.sleep(5)
                    r1 = k8s.exec_command(f'kubectl get pods -n {ns_middleware} --no-headers 2>/dev/null | wc -l')
                    r2 = k8s.exec_command(f'kubectl get pods -n {ns_service} --no-headers 2>/dev/null | wc -l')
                    count_mw = int(r1['stdout']) if r1['stdout'].isdigit() else 0
                    count_svc = int(r2['stdout']) if r2['stdout'].isdigit() else 0
                    if count_mw == 0 and count_svc == 0:
                        log('OK', f'  所有Pod已终止（尝试{attempt+1}/6）')
                        break
                    log('INFO', f'  等待中（尝试{attempt+1}/6）: middleware={count_mw}, service={count_svc}')
                else:
                    # 30秒后仍有Pod，强制删除
                    log('WARN', '  30秒后仍有Pod未终止，执行强制删除...')
                    for ns in [ns_middleware, ns_service]:
                        r = k8s.exec_command(f'kubectl get pods -n {ns} --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null')
                        if r['stdout']:
                            for pod_name in r['stdout'].split('\n'):
                                pod_name = pod_name.strip()
                                if pod_name:
                                    r2 = k8s.exec_command(f'kubectl delete pod {pod_name} -n {ns} --force --grace-period=0')
                                    if r2['exit_code'] == 0:
                                        log('OK', f'  已强制删除Pod: {pod_name}')
                                    else:
                                        log('WARN', f'  强制删除失败: {pod_name} - {r2["stderr"]}')
                    # 等待强制删除生效
                    for attempt2 in range(6):
                        time.sleep(5)
                        r1 = k8s.exec_command(f'kubectl get pods -n {ns_middleware} --no-headers 2>/dev/null | wc -l')
                        r2 = k8s.exec_command(f'kubectl get pods -n {ns_service} --no-headers 2>/dev/null | wc -l')
                        count_mw = int(r1['stdout']) if r1['stdout'].isdigit() else 0
                        count_svc = int(r2['stdout']) if r2['stdout'].isdigit() else 0
                        if count_mw == 0 and count_svc == 0:
                            log('OK', '  强制删除后所有Pod已终止')
                            force_deleted = True
                            break
                    if not force_deleted:
                        log('WARN', f'  仍有Pod残留: middleware={count_mw}, service={count_svc}')

                success_count += 1
                log('OK', 'K8s资源清理完成')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'K8s资源清理失败: {str(e)}')

            # 步骤2: NFS回收
            log('INFO', 'NFS目录回收...', step=f'步骤2/{total_steps}')
            log('INFO', f'回收目标: {env_full}，回收站: /data/recycle/')
            try:
                nfs = NFSService()
                nfs_result = nfs.recycle_project_dirs(project_name, env_name)
                moved = nfs_result.get('moved', 0)
                skipped = nfs_result.get('skipped', 0)
                failed = nfs_result.get('failed', 0)
                recycle_dir_path = nfs_result.get('recycle_dir', '')
                if recycle_dir_path:
                    recycle_info['nfs_recycle_dir'] = recycle_dir_path
                    log('INFO', f'回收站目录: {recycle_dir_path}')
                # 打印每个移动详情
                for item in nfs_result.get('details', []):
                    log('INFO', f'  已移动: {item.get("source", "")} -> {item.get("dest", "")}')
                # 打印跳过和错误
                for item in nfs_result.get('errors', []):
                    log('WARN', f'  失败: {item.get("source", "")} - {item.get("error", "")}')
                if failed > 0:
                    log('WARN', f'NFS回收: {moved}成功, {skipped}跳过, {failed}失败')
                else:
                    log('OK', f'NFS回收完成: {moved}个目录已移动, {skipped}个跳过')
                success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'NFS回收失败: {str(e)}')

            # 步骤3: Harbor删除
            log('INFO', 'Harbor项目删除...', step=f'步骤3/{total_steps}')
            log('INFO', f'目标项目: {env_full}')
            try:
                harbor = get_harbor_client()
                harbor_project = harbor.get_project(env_full)
                if harbor_project:
                    # 先查询仓库数量
                    repos = harbor.get_repositories(env_full, page_size=50)
                    repo_count = len(repos) if repos else 0
                    if repo_count > 0:
                        log('INFO', f'发现 {repo_count} 个仓库，开始清理...')
                        for repo in repos:
                            repo_name = repo.get('name', '').split('/', 1)[-1]
                            log('INFO', f'  删除仓库: {repo_name}')
                    del_result = harbor.delete_project(env_full)
                    if del_result['success']:
                        log('OK', f'Harbor项目已删除: {env_full}（含{repo_count}个仓库）')
                        success_count += 1
                    else:
                        log('WARN', f'Harbor删除失败: {del_result.get("message", "")}')
                        fail_count += 1
                else:
                    log('INFO', f'Harbor项目 {env_full} 不存在，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Harbor删除失败: {str(e)}')

            # 步骤4: YAML文件回收
            log('INFO', 'YAML文件回收...', step=f'步骤4/{total_steps}')
            try:
                output_dir_setting = Setting.query.filter_by(key='yaml_output_dir').first()
                output_dir = output_dir_setting.value if output_dir_setting else './output'
                yaml_dir = os.path.join(output_dir, env_full)
                log('INFO', f'源目录: {yaml_dir}')
                if os.path.exists(yaml_dir):
                    # 列出子目录和文件
                    sub_items = os.listdir(yaml_dir)
                    for sub in sub_items:
                        sub_path = os.path.join(yaml_dir, sub)
                        if os.path.isdir(sub_path):
                            file_count = len([f for f in os.listdir(sub_path) if f.endswith(('.yaml', '.yml'))])
                            log('INFO', f'  子目录: {sub}/ ({file_count}个YAML文件)')
                        else:
                            log('INFO', f'  文件: {sub}')
                    recycle_dir_setting = Setting.query.filter_by(key='yaml_recycle_dir').first()
                    recycle_base = recycle_dir_setting.value if recycle_dir_setting else './recycle'
                    recycle_dest = os.path.join(recycle_base, f"{env_full}-{timestamp}")
                    os.makedirs(recycle_base, exist_ok=True)
                    shutil.move(yaml_dir, recycle_dest)
                    recycle_info['yaml_recycle_path'] = recycle_dest
                    log('OK', f'YAML已移动: {yaml_dir} -> {recycle_dest}')
                    success_count += 1
                else:
                    log('INFO', f'YAML目录不存在: {yaml_dir}，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'YAML回收失败: {str(e)}')

            # 步骤5: 远程YAML回收
            log('INFO', '远程YAML回收...', step=f'步骤5/{total_steps}')
            try:
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_recycle_base = get_k8s_yaml_remote_recycle_dir()
                remote_dir = f"{remote_yaml_dir}/{env_full}"
                remote_recycle_dest = f"{remote_recycle_base}/{env_full}-{timestamp}"
                if k8s.remote_directory_exists(remote_dir):
                    k8s.move_directory(remote_dir, remote_recycle_dest)
                    recycle_info['k8s_remote_recycle_path'] = remote_recycle_dest
                    log('OK', f'远程YAML已移到回收站: {remote_recycle_dest}')
                    success_count += 1
                else:
                    log('INFO', f'远程目录不存在: {remote_dir}，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'远程YAML回收失败: {str(e)}')

            # 步骤6: Nginx配置回收
            log('INFO', 'Nginx配置回收（移入回收站）...', step=f'步骤6/{total_steps}')
            try:
                domain = env.domain or ''
                if domain:
                    nginx_recycle_info = _recycle_nginx_config(domain, timestamp, log)
                    if nginx_recycle_info:
                        recycle_info['nginx_conf'] = nginx_recycle_info
                    success_count += 1
                else:
                    log('INFO', '环境无域名记录，跳过Nginx回收')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Nginx配置回收失败: {str(e)}')

            # 步骤7: 数据库标记删除
            log('INFO', '数据库记录标记删除...', step=f'步骤7/{total_steps}')
            log('INFO', f'环境ID: {env_id}, 项目: {project_name}, 环境: {env_name}')
            try:
                env.is_deleted = True
                env.deleted_at = dt.now()
                env.recycle_info = json.dumps(recycle_info) if recycle_info else None
                db.session.commit()
                log('INFO', f'回收信息已保存: {json.dumps(recycle_info, ensure_ascii=False)}')
                log('OK', f'数据库记录已标记为已删除 (deleted_at={env.deleted_at.strftime("%Y-%m-%d %H:%M:%S")})')
                success_count += 1
            except Exception as e:
                db.session.rollback()
                fail_count += 1
                log('ERROR', f'数据库删除失败: {str(e)}')

            # 完成
            elapsed = (dt.now() - dt.strptime(
                _deploy_tasks.get(task_key, {}).get('started_at', dt.now().isoformat())[:19],
                '%Y-%m-%dT%H:%M:%S'
            )).total_seconds()
            if fail_count == 0:
                log('DONE', f'回收完成，共{total_steps}步，全部成功，耗时{elapsed:.1f}秒')
            else:
                log('DONE', f'回收完成，共{total_steps}步，成功{success_count}，失败{fail_count}，耗时{elapsed:.1f}秒')

            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'completed'

        except Exception as e:
            log('FAILED', f'回收异常终止: {str(e)}')
            import traceback
            log('ERROR', traceback.format_exc())
            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'failed'


# ─── 恢复任务 ─────────────────────────────────────────────

def _run_restore_task(app, task_key, env_id):
    """后台线程：执行环境恢复并写入日志"""
    with app.app_context():
        from modules.deploy.services.nfs_service import NFSService
        from modules.deploy.services.k8s_service import K8sService
        from modules.deploy.api.shared import get_k8s_yaml_remote_dir, get_k8s_yaml_remote_recycle_dir
        from datetime import datetime as dt

        env = Environment.query.get(env_id)
        if not env:
            return
        project = env.project
        if not project:
            return

        project_name = project.name
        env_name = env.name
        env_full = f"{project_name}-{env_name}"
        log_file = _get_log_path(project_name, env_name, 'restore')

        def log(level, message, step=None):
            _write_log(log_file, level, message, step)

        with _tasks_lock:
            _deploy_tasks[task_key] = {
                'status': 'running', 'log_file': log_file,
                'started_at': dt.now().isoformat(),
                'project_name': project_name, 'env_name': env_name
            }

        recycle_info = json.loads(env.recycle_info) if env.recycle_info else {}
        success_count = 0
        fail_count = 0
        total_steps = 7

        try:
            # 步骤1: NFS恢复
            log('INFO', 'NFS目录恢复...', step=f'步骤1/{total_steps}')
            log('INFO', f'恢复目标: {env_full}')
            try:
                nfs = NFSService()
                nfs_recycle_dir = recycle_info.get('nfs_recycle_dir')
                if nfs_recycle_dir:
                    log('INFO', f'回收站路径: {nfs_recycle_dir}')
                else:
                    log('INFO', '无回收路径记录，尝试自动搜索...')
                    nfs_recycle_dir = nfs.find_latest_recycle_dir(project_name, env_name)
                    if nfs_recycle_dir:
                        log('INFO', f'自动搜索到回收目录: {nfs_recycle_dir}')
                    else:
                        log('WARN', '未找到任何回收目录')

                restored = 0
                skipped = 0
                failed = 0

                if nfs_recycle_dir:
                    nfs_result = nfs.restore_project_dirs(project_name, env_name, nfs_recycle_dir)
                    restored = nfs_result.get('restored', 0)
                    skipped = nfs_result.get('skipped', 0)
                    failed = nfs_result.get('failed', 0)
                    # 打印每个恢复详情
                    for item in nfs_result.get('details', []):
                        log('INFO', f'  已还原: {item.get("source", "")} -> {item.get("dest", "")}')
                    for item in nfs_result.get('errors', []):
                        log('WARN', f'  失败: {item.get("source", "")} -> {item.get("dest", "")} - {item.get("error", "")}')

                # 无论回收站是否存在，都尝试创建缺失目录
                log('INFO', '检查并创建缺失目录...')
                deploy_config = json.loads(env.deploy_config) if env.deploy_config else {}
                services_list = deploy_config.get('services', [])
                create_result = nfs.create_project_dirs(project_name, env_name, services_list)
                created = create_result.get('created', 0)
                create_skipped = create_result.get('skipped', 0)
                create_failed = create_result.get('failed', 0)

                if created > 0:
                    for item in create_result.get('dirs', []):
                        log('INFO', f'  新创建: {item.get("path", "")} ({item.get("type", "")})')
                for item in create_result.get('skipped_dirs', []):
                    log('INFO', f'  已存在: {item.get("path", "")} ({item.get("type", "")})')
                for item in create_result.get('errors', []):
                    log('ERROR', f'  创建失败: {item.get("path", "")} - {item.get("error", "")}')
                    failed += 1

                if failed > 0:
                    log('WARN', f'NFS恢复: {restored}还原, {created}新创建, {create_skipped}已存在, {failed}失败')
                else:
                    log('OK', f'NFS恢复完成: {restored}个还原, {created}个新创建, {create_skipped}个已存在')
                success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'NFS恢复失败: {str(e)}')

            # 步骤2: Harbor重建
            log('INFO', 'Harbor项目重建...', step=f'步骤2/{total_steps}')
            log('INFO', f'目标项目: {env_full}')
            try:
                harbor_result = _create_harbor_project_step(project_name, env_name, log=log)
                if harbor_result.get('status') != 'failed':
                    log('OK', f'Harbor项目就绪: {harbor_result.get("status")}，项目名: {harbor_result.get("project_name", env_full)}')
                    success_count += 1
                else:
                    log('WARN', f'Harbor重建失败: {harbor_result.get("error")}')
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Harbor重建异常: {str(e)}')

            # 步骤3: YAML文件恢复
            log('INFO', 'YAML文件恢复...', step=f'步骤3/{total_steps}')
            try:
                yaml_recycle_path = recycle_info.get('yaml_recycle_path')
                if yaml_recycle_path:
                    log('INFO', f'回收路径: {yaml_recycle_path}')
                else:
                    log('INFO', '无回收路径记录，尝试自动搜索...')
                    recycle_dir_setting = Setting.query.filter_by(key='yaml_recycle_dir').first()
                    recycle_base = recycle_dir_setting.value if recycle_dir_setting else './recycle'
                    if os.path.isdir(recycle_base):
                        import glob
                        matches = sorted(glob.glob(os.path.join(recycle_base, f"{env_full}-*")))
                        if matches:
                            yaml_recycle_path = matches[-1]
                            log('INFO', f'自动搜索到YAML回收目录: {yaml_recycle_path}')
                        else:
                            log('WARN', f'回收站中未找到 {env_full}-* 目录')
                if yaml_recycle_path and os.path.exists(yaml_recycle_path):
                    output_dir_setting = Setting.query.filter_by(key='yaml_output_dir').first()
                    output_dir = output_dir_setting.value if output_dir_setting else './output'
                    yaml_dest = os.path.join(output_dir, env_full)
                    os.makedirs(os.path.dirname(yaml_dest), exist_ok=True)
                    # 列出恢复的子目录
                    sub_items = os.listdir(yaml_recycle_path)
                    for sub in sub_items:
                        sub_path = os.path.join(yaml_recycle_path, sub)
                        if os.path.isdir(sub_path):
                            file_count = len([f for f in os.listdir(sub_path) if f.endswith(('.yaml', '.yml'))])
                            log('INFO', f'  还原子目录: {sub}/ ({file_count}个YAML文件)')
                        else:
                            log('INFO', f'  还原文件: {sub}')
                    shutil.move(yaml_recycle_path, yaml_dest)
                    log('OK', f'YAML已还原: {yaml_recycle_path} -> {yaml_dest}')
                    success_count += 1
                else:
                    log('WARN', f'YAML回收目录不存在，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'YAML恢复失败: {str(e)}')

            # 步骤4: 远程YAML恢复
            log('INFO', '远程YAML恢复...', step=f'步骤4/{total_steps}')
            try:
                k8s = K8sService()
                remote_recycle_path = recycle_info.get('k8s_remote_recycle_path')
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{env_full}"
                if remote_recycle_path and k8s.remote_directory_exists(remote_recycle_path):
                    k8s.move_directory(remote_recycle_path, remote_dir)
                    log('OK', f'远程YAML已恢复: {remote_recycle_path} -> {remote_dir}')
                    success_count += 1
                else:
                    log('INFO', f'远程回收目录不存在，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'远程YAML恢复失败: {str(e)}')

            # 步骤5: 数据库记录恢复
            log('INFO', '数据库记录恢复...', step=f'步骤5/{total_steps}')
            log('INFO', f'环境ID: {env_id}, 项目: {project_name}, 环境: {env_name}')
            try:
                env.is_deleted = False
                env.deleted_at = None
                env.recycle_info = None
                db.session.commit()
                log('OK', f'数据库记录已恢复 (is_deleted=False, recycle_info=None)')
                success_count += 1
            except Exception as e:
                db.session.rollback()
                fail_count += 1
                log('ERROR', f'数据库恢复失败: {str(e)}')

            # 步骤6: K8s资源恢复（重新apply中间件YAML + 服务YAML，mysql扩容）
            log('INFO', 'K8s资源恢复...', step=f'步骤6/{total_steps}')
            ns_middleware = f"{env_full}-middleware"
            ns_service = f"{env_full}-service"
            log('INFO', f'  中间件Namespace: {ns_middleware}')
            log('INFO', f'  服务Namespace: {ns_service}')
            try:
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{env_full}"

                # 1. 重新apply中间件YAML（恢复被删除的StatefulSet）
                log('INFO', '  [中间件] 重新apply YAML...')
                r = k8s.exec_command(f'ls {remote_dir}/middleware/ 2>/dev/null')
                if r['stdout']:
                    for yaml_file in r['stdout'].split('\n'):
                        yaml_file = yaml_file.strip()
                        if yaml_file.endswith('.yaml'):
                            yaml_path = f"{remote_dir}/middleware/{yaml_file}"
                            # public-config.yaml 特殊处理：内嵌namespace，直接apply
                            if yaml_file == 'public-config.yaml':
                                r2 = k8s.exec_command(f'kubectl apply -f {yaml_path}')
                                # 同时应用到middleware namespace（去除namespace字段）
                                r3 = k8s.exec_command(f"cat {yaml_path} | sed '/^  namespace:/d' | kubectl apply -n {ns_middleware} -f -")
                                if r2['exit_code'] == 0 or r3['exit_code'] == 0:
                                    log('OK', f'  已应用: {yaml_file}（service + middleware namespace）')
                                else:
                                    log('WARN', f'  应用失败: {yaml_file}')
                            else:
                                r2 = k8s.exec_command(f'kubectl apply -f {yaml_path}')
                                if r2['exit_code'] == 0:
                                    log('OK', f'  已应用: {yaml_file}')
                                else:
                                    log('WARN', f'  应用失败: {yaml_file} - {r2["stderr"]}')

                # 2. 重新apply服务Deployment YAML
                log('INFO', f'  [服务] 重新apply YAML（{ns_service}）...')
                r = k8s.exec_command(f'ls {remote_dir}/deployment/ 2>/dev/null')
                if r['stdout']:
                    for yaml_file in r['stdout'].split('\n'):
                        yaml_file = yaml_file.strip()
                        if yaml_file.endswith('.yaml'):
                            yaml_path = f"{remote_dir}/deployment/{yaml_file}"
                            r2 = k8s.exec_command(f'kubectl apply -f {yaml_path}')
                            if r2['exit_code'] == 0:
                                log('OK', f'  已应用: deployment/{yaml_file}')
                            else:
                                log('WARN', f'  应用失败: {yaml_file} - {r2["stderr"]}')

                r = k8s.exec_command(f'ls {remote_dir}/service/ 2>/dev/null')
                if r['stdout']:
                    for yaml_file in r['stdout'].split('\n'):
                        yaml_file = yaml_file.strip()
                        if yaml_file.endswith('.yaml'):
                            yaml_path = f"{remote_dir}/service/{yaml_file}"
                            r2 = k8s.exec_command(f'kubectl apply -f {yaml_path}')
                            if r2['exit_code'] == 0:
                                log('OK', f'  已应用: service/{yaml_file}')
                            else:
                                log('WARN', f'  应用失败: {yaml_file} - {r2["stderr"]}')

                # 3. MySQL StatefulSet 扩容（PVC数据保留，恢复到1副本）
                log('INFO', '  [MySQL] 扩容到1副本（PVC数据恢复）...')
                r = k8s.exec_command(f'kubectl get statefulset -n {ns_middleware} -o name')
                if r['stdout']:
                    for res_name in r['stdout'].split('\n'):
                        res_name = res_name.strip()
                        if res_name and 'mysql' in res_name.lower() and 'nfs' not in res_name.lower():
                            r2 = k8s.exec_command(f'kubectl scale {res_name} --replicas=1 -n {ns_middleware}')
                            if r2['exit_code'] == 0:
                                log('OK', f'  已扩容: {res_name} -> 1（PVC数据恢复）')
                            else:
                                log('WARN', f'  扩容失败: {res_name} - {r2["stderr"]}')

                success_count += 1
                log('OK', 'K8s资源恢复完成，Pod正在启动')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'K8s资源恢复失败: {str(e)}')

            # 步骤7: Nginx配置恢复
            log('INFO', 'Nginx配置恢复（从回收站移回）...', step=f'步骤7/{total_steps}')
            try:
                domain = env.domain or ''
                if domain:
                    _restore_nginx_config(domain, recycle_info.get('nginx_conf'), log)
                    success_count += 1
                else:
                    log('INFO', '环境无域名记录，跳过Nginx恢复')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Nginx配置恢复失败: {str(e)}')

            # 完成
            elapsed = (dt.now() - dt.strptime(
                _deploy_tasks.get(task_key, {}).get('started_at', dt.now().isoformat())[:19],
                '%Y-%m-%dT%H:%M:%S'
            )).total_seconds()
            if fail_count == 0:
                log('DONE', f'恢复完成，共{total_steps}步，全部成功，耗时{elapsed:.1f}秒')
            else:
                log('DONE', f'恢复完成，共{total_steps}步，成功{success_count}，失败{fail_count}，耗时{elapsed:.1f}秒')

            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'completed'

        except Exception as e:
            log('FAILED', f'恢复异常终止: {str(e)}')
            import traceback
            log('ERROR', traceback.format_exc())
            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'failed'


# ─── 彻底删除任务 ─────────────────────────────────────

def _run_permanent_delete_task(app, task_key, env_id):
    """后台线程：执行彻底删除并写入日志"""
    with app.app_context():
        from modules.deploy.services.nfs_service import NFSService
        from modules.deploy.services.k8s_service import K8sService
        from modules.deploy.api.shared import get_k8s_yaml_remote_dir
        from datetime import datetime as dt

        env = Environment.query.get(env_id)
        if not env:
            return
        project = env.project
        if not project:
            return

        project_name = project.name
        env_name = env.name
        env_full = f"{project_name}-{env_name}"
        log_file = _get_log_path(project_name, env_name, 'permanent-delete')

        def log(level, message, step=None):
            _write_log(log_file, level, message, step)

        with _tasks_lock:
            _deploy_tasks[task_key] = {
                'status': 'running', 'log_file': log_file,
                'started_at': dt.now().isoformat(),
                'project_name': project_name, 'env_name': env_name
            }

        recycle_info = json.loads(env.recycle_info) if env.recycle_info else {}
        success_count = 0
        fail_count = 0
        total_steps = 8

        try:
            # 步骤1: 删除本地YAML回收目录
            log('INFO', '删除本地YAML回收目录...', step=f'步骤1/{total_steps}')
            yaml_recycle_path = recycle_info.get('yaml_recycle_path')
            try:
                if yaml_recycle_path and os.path.exists(yaml_recycle_path):
                    shutil.rmtree(yaml_recycle_path)
                    log('OK', f'已删除: {yaml_recycle_path}')
                    success_count += 1
                else:
                    log('INFO', f'本地YAML回收目录不存在，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'删除本地YAML失败: {str(e)}')

            # 步骤2: 删除NFS回收目录
            log('INFO', '删除NFS回收目录...', step=f'步骤2/{total_steps}')
            nfs_recycle_dir = recycle_info.get('nfs_recycle_dir')
            try:
                if nfs_recycle_dir:
                    nfs = NFSService()
                    if nfs.directory_exists(nfs_recycle_dir):
                        nfs.remove_directory(nfs_recycle_dir)
                        log('OK', f'已删除: {nfs_recycle_dir}')
                        success_count += 1
                    else:
                        log('INFO', f'NFS回收目录不存在，跳过')
                        success_count += 1
                else:
                    log('INFO', '无NFS回收路径记录，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'删除NFS目录失败: {str(e)}')

            # 步骤3: 删除远程K8s YAML回收目录
            log('INFO', '删除远程K8s YAML回收目录...', step=f'步骤3/{total_steps}')
            k8s_remote_recycle_path = recycle_info.get('k8s_remote_recycle_path')
            try:
                if k8s_remote_recycle_path:
                    k8s = K8sService()
                    if k8s.remote_directory_exists(k8s_remote_recycle_path):
                        k8s.remove_directory(k8s_remote_recycle_path)
                        log('OK', f'已删除: {k8s_remote_recycle_path}')
                        success_count += 1
                    else:
                        log('INFO', f'远程YAML回收目录不存在，跳过')
                        success_count += 1
                else:
                    log('INFO', '无远程YAML回收路径记录，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'删除远程YAML回收目录失败: {str(e)}')

            # 步骤4: 删除远程K8s YAML正式目录（兆底）
            log('INFO', '删除远程K8s YAML正式目录...', step=f'步骤4/{total_steps}')
            try:
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{env_full}"
                if k8s.remote_directory_exists(remote_dir):
                    k8s.remove_directory(remote_dir)
                    log('OK', f'已删除: {remote_dir}')
                    success_count += 1
                else:
                    log('INFO', f'远程YAML目录不存在，跳过')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'删除远程YAML目录失败: {str(e)}')

            # 步骤5: 删除K8s Namespace（会同时删除PVC和存储卷数据，不可恢复）
            log('INFO', '删除K8s Namespace...', step=f'步骤5/{total_steps}')
            ns_middleware = f"{env_full}-middleware"
            ns_service = f"{env_full}-service"
            log('INFO', f'  中间件Namespace: {ns_middleware}（含PVC存储卷数据，不可恢复）')
            log('INFO', f'  服务Namespace: {ns_service}')
            try:
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{env_full}"

                def check_and_clean_resources(ns, remote_sub_dirs, label=''):
                    """检查namespace内是否有残留资源，有则重新执行delete -f清理"""
                    r = k8s.exec_command(f'kubectl get pods -n {ns} --no-headers 2>/dev/null | wc -l')
                    count = int(r['stdout']) if r['stdout'] and r['stdout'].strip().isdigit() else 0
                    if count == 0:
                        log('INFO', f'  {ns} {label}无残留资源')
                        return
                    log('WARN', f'  {ns} {label}发现{count}个残留Pod，重新执行delete -f清理...')
                    for sub_dir in remote_sub_dirs:
                        r2 = k8s.exec_command(f'ls {remote_dir}/{sub_dir}/ 2>/dev/null')
                        if r2['stdout']:
                            for yaml_file in r2['stdout'].split('\n'):
                                yaml_file = yaml_file.strip()
                                if yaml_file.endswith('.yaml') and yaml_file != 'mysql.yaml' and yaml_file != 'public-config.yaml':
                                    yaml_path = f"{remote_dir}/{sub_dir}/{yaml_file}"
                                    r3 = k8s.exec_command(f'kubectl delete -f {yaml_path} --ignore-not-found')
                                    if r3['exit_code'] == 0:
                                        log('OK', f'  已清理: {sub_dir}/{yaml_file}')
                    # 等待资源终止（30秒后强制删除）
                    for attempt in range(6):
                        time.sleep(5)
                        r4 = k8s.exec_command(f'kubectl get pods -n {ns} --no-headers 2>/dev/null | wc -l')
                        c = int(r4['stdout']) if r4['stdout'] and r4['stdout'].strip().isdigit() else 0
                        if c == 0:
                            log('OK', f'  {ns} {label}资源已清理完毕')
                            return
                        log('INFO', f'  等待{ns}资源终止（尝试{attempt+1}/6）: {c}个Pod')
                    # 30秒后仍有Pod，强制删除
                    log('WARN', f'  {ns} 30秒后仍有Pod，强制删除...')
                    r5 = k8s.exec_command(f'kubectl get pods -n {ns} --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null')
                    if r5['stdout']:
                        for pod_name in r5['stdout'].split('\n'):
                            pod_name = pod_name.strip()
                            if pod_name:
                                r6 = k8s.exec_command(f'kubectl delete pod {pod_name} -n {ns} --force --grace-period=0')
                                if r6['exit_code'] == 0:
                                    log('OK', f'  已强制删除Pod: {pod_name}')

                import time
                # 清理中间件残留资源
                check_and_clean_resources(ns_middleware, ['middleware'], '（中间件）')
                # 清理服务残留资源
                check_and_clean_resources(ns_service, ['deployment', 'service'], '（服务）')

                def delete_namespace(ns, label=''):
                    """删除namespace，30秒超时后强制清理finalizer"""
                    log('INFO', f'  删除Namespace: {ns} {label}...')
                    # 正常删除，30秒超时
                    r = k8s.exec_command(f'kubectl delete namespace {ns} --ignore-not-found --timeout=30s', timeout=40)
                    # 检查是否还存在
                    r2 = k8s.exec_command(f'kubectl get namespace {ns} -o name 2>/dev/null')
                    if r2['stdout'] and f'namespace/{ns}' in r2['stdout']:
                        # 还在，可能卡在 Terminating，强制删除 finalizer
                        log('WARN', f'  {ns} 未删除，可能卡在Terminating，强制清理...')
                        r3 = k8s.exec_command(
                            f"kubectl get namespace {ns} -o json | "
                            f"sed 's/\"finalizers\": \\[[^]]*\\]/\"finalizers\": []/' | "
                            f"kubectl replace --raw \"/api/v1/namespaces/{ns}/finalize\" -f -"
                        )
                        if r3['exit_code'] == 0:
                            log('OK', f'  已强制删除: {ns} {label}')
                        else:
                            log('WARN', f'  强制删除失败: {ns} - {r3["stderr"]}')
                    else:
                        log('OK', f'  已删除: {ns} {label}')

                delete_namespace(ns_middleware, '（含PVC存储卷数据）')
                delete_namespace(ns_service)
                success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'删除K8s Namespace失败: {str(e)}')

            # 步骤6: Nginx配置清理（删除回收站文件）
            log('INFO', 'Nginx配置清理...', step=f'步骤6/{total_steps}')
            try:
                domain = env.domain or ''
                if domain:
                    _delete_nginx_config_recycle(recycle_info.get('nginx_conf'), domain, log)
                    success_count += 1
                else:
                    log('INFO', '环境无域名记录，跳过Nginx清理')
                    success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Nginx配置清理失败: {str(e)}')

            # 步骤7: 清理关联记录（构建记录/调度日志）
            log('INFO', '清理关联记录（构建记录/调度日志）...', step=f'步骤7/{total_steps}')
            try:
                from modules.cicd.models import Build, ScheduleLog
                build_ids = [b.id for b in db.session.query(Build.id).filter_by(environment_id=env_id).all()]
                if build_ids:
                    sch_count = ScheduleLog.query.filter(ScheduleLog.build_id.in_(build_ids)).delete(synchronize_session=False)
                    bld_count = Build.query.filter(Build.id.in_(build_ids)).delete(synchronize_session=False)
                    db.session.commit()
                    log('OK', f'已清理: 构建记录{bld_count}条, 调度日志{sch_count}条')
                else:
                    log('INFO', '无构建记录，跳过')
                success_count += 1
            except Exception as e:
                db.session.rollback()
                fail_count += 1
                log('ERROR', f'清理关联记录失败: {str(e)}')

            # 步骤8: 删除数据库记录
            log('INFO', '删除数据库记录...', step=f'步骤8/{total_steps}')
            log('INFO', f'环境ID: {env_id}, 项目: {project_name}, 环境: {env_name}')
            try:
                db.session.delete(env)
                db.session.commit()
                log('OK', '数据库记录已删除')
                success_count += 1
            except Exception as e:
                db.session.rollback()
                fail_count += 1
                log('ERROR', f'删除数据库记录失败: {str(e)}')

            # 完成
            elapsed = (dt.now() - dt.strptime(
                _deploy_tasks.get(task_key, {}).get('started_at', dt.now().isoformat())[:19],
                '%Y-%m-%dT%H:%M:%S'
            )).total_seconds()
            if fail_count == 0:
                log('DONE', f'彻底删除完成，共{total_steps}步，全部成功，耗时{elapsed:.1f}秒')
            else:
                log('DONE', f'彻底删除完成，共{total_steps}步，成功{success_count}，失败{fail_count}，耗时{elapsed:.1f}秒')

            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'completed'

        except Exception as e:
            log('FAILED', f'彻底删除异常终止: {str(e)}')
            import traceback
            log('ERROR', traceback.format_exc())
            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'failed'


def _run_batch_task(app, task_key, env_ids, single_task_func, action_label):
    """通用批量任务执行器：逐个串行调用单个任务函数"""
    with app.app_context():
        from datetime import datetime as dt

        batch_log_dir = os.path.join('logs', 'batch')
        os.makedirs(batch_log_dir, exist_ok=True)
        batch_log = os.path.join(batch_log_dir, f'batch-{action_label}-{dt.now().strftime("%Y%m%d_%H%M%S")}.log')

        def log(level, message, step=None):
            _write_log(batch_log, level, message, step)

        with _tasks_lock:
            _deploy_tasks[task_key] = {
                'status': 'running', 'log_file': batch_log,
                'started_at': dt.now().isoformat(),
                'project_name': 'batch', 'env_name': 'batch'
            }

        total = len(env_ids)
        all_success = True
        log('INFO', f'===== 开始批量{action_label}: 共{total}个环境 =====')

        for i, env_id in enumerate(env_ids, 1):
            env = Environment.query.get(env_id)
            if not env:
                log('ERROR', f'[{i}/{total}] 环境ID {env_id} 不存在，跳过')
                all_success = False
                continue
            project = env.project
            if not project:
                log('ERROR', f'[{i}/{total}] 环境ID {env_id} 关联项目不存在，跳过')
                all_success = False
                continue

            project_name = project.name
            env_name = env.name
            env_full = f'{project_name}-{env_name}'
            log('INFO', f'[{i}/{total}] {env_full} ▶ 开始{action_label}...')

            # 构造子任务 key
            suffix_map = {'\u56de\u6536': '-recycle', '\u6062\u590d': '-restore', '\u5f7b\u5e95\u5220\u9664': '-permanent-delete'}
            suffix = suffix_map.get(action_label, '')
            sub_key = f'{project_name}-{env_name}{suffix}'

            with _tasks_lock:
                existing = _deploy_tasks.get(sub_key)
                if existing and existing.get('status') == 'running':
                    log('WARN', f'[{i}/{total}] {env_full} ⚠ 该环境正在操作中，跳过')
                    all_success = False
                    continue

            try:
                single_task_func(app, sub_key, env_id)
                # 检查子任务状态
                with _tasks_lock:
                    sub_status = _deploy_tasks.get(sub_key, {}).get('status', '')
                if sub_status == 'failed':
                    all_success = False
                    log('ERROR', f'[{i}/{total}] {env_full} ✘ {action_label}失败')
                else:
                    log('OK', f'[{i}/{total}] {env_full} ✔ {action_label}成功')
            except Exception as e:
                all_success = False
                log('ERROR', f'[{i}/{total}] {env_full} ✘ {action_label}异常: {str(e)}')

            log('INFO', '')  # 空行分隔

        # 批量完成
        elapsed = (dt.now() - dt.strptime(
            _deploy_tasks.get(task_key, {}).get('started_at', dt.now().isoformat())[:19],
            '%Y-%m-%dT%H:%M:%S'
        )).total_seconds()
        if all_success:
            log('DONE', f'批量{action_label}完成，共{total}个环境，全部成功，耗时{elapsed:.1f}秒')
        else:
            log('DONE', f'批量{action_label}完成，共{total}个环境，部分失败，耗时{elapsed:.1f}秒')

        with _tasks_lock:
            _deploy_tasks[task_key]['status'] = 'completed' if all_success else 'failed'


def _run_batch_recycle_task(app, task_key, env_ids):
    """批量回收"""
    _run_batch_task(app, task_key, env_ids, _run_recycle_task, '\u56de\u6536')


def _run_batch_restore_task(app, task_key, env_ids):
    """批量恢复"""
    _run_batch_task(app, task_key, env_ids, _run_restore_task, '\u6062\u590d')


def _run_batch_permanent_delete_task(app, task_key, env_ids):
    """后台线程：批量彻底删除，逐个串行执行"""
    with app.app_context():
        from datetime import datetime as dt

        # 批量日志文件
        batch_log_dir = os.path.join('logs', 'batch')
        os.makedirs(batch_log_dir, exist_ok=True)
        batch_log = os.path.join(batch_log_dir, f'batch-permanent-delete-{dt.now().strftime("%Y%m%d_%H%M%S")}.log')

        def log(level, message, step=None):
            _write_log(batch_log, level, message, step)

        with _tasks_lock:
            _deploy_tasks[task_key] = {
                'status': 'running', 'log_file': batch_log,
                'started_at': dt.now().isoformat(),
                'project_name': 'batch', 'env_name': 'batch'
            }

        total = len(env_ids)
        all_success = True
        log('INFO', f'===== 开始批量彻底删除: 共{total}个环境 =====')

        for i, env_id in enumerate(env_ids, 1):
            env = Environment.query.get(env_id)
            if not env:
                log('ERROR', f'[{i}/{total}] 环境ID {env_id} 不存在，跳过')
                all_success = False
                continue
            project = env.project
            if not project:
                log('ERROR', f'[{i}/{total}] 环境ID {env_id} 关联项目不存在，跳过')
                all_success = False
                continue

            project_name = project.name
            env_name = env.name
            env_full = f'{project_name}-{env_name}'
            prefix = f'[{i}/{total}] {env_full}'
            log('INFO', f'{prefix} ▶ 开始彻底删除...')

            # 为单个环境创建子任务（用于并发冲突检测）
            sub_key = f'{project_name}-{env_name}-permanent-delete'
            with _tasks_lock:
                existing = _deploy_tasks.get(sub_key)
                if existing and existing.get('status') == 'running':
                    log('WARN', f'{prefix} ⚠ 该环境正在操作中，跳过')
                    all_success = False
                    continue
                _deploy_tasks[sub_key] = {
                    'status': 'running', 'log_file': batch_log,
                    'started_at': dt.now().isoformat(),
                    'project_name': project_name, 'env_name': env_name
                }

            try:
                _execute_permanent_delete_steps(env, env_id, batch_log, prefix)
                log('OK', f'{prefix} ✔ 删除成功')
            except Exception as e:
                all_success = False
                log('ERROR', f'{prefix} ✘ 删除失败: {str(e)}')

            with _tasks_lock:
                _deploy_tasks[sub_key]['status'] = 'completed'

            log('INFO', '')  # 空行分隔

        # 批量完成
        elapsed = (dt.now() - dt.strptime(
            _deploy_tasks.get(task_key, {}).get('started_at', dt.now().isoformat())[:19],
            '%Y-%m-%dT%H:%M:%S'
        )).total_seconds()
        if all_success:
            log('DONE', f'批量彻底删除完成，共{total}个环境，全部成功，耗时{elapsed:.1f}秒')
        else:
            log('DONE', f'批量彻底删除完成，共{total}个环境，部分失败，耗时{elapsed:.1f}秒')

        with _tasks_lock:
            _deploy_tasks[task_key]['status'] = 'completed' if all_success else 'failed'


def _execute_permanent_delete_steps(env, env_id, log_file, prefix=''):
    """执行单个环境的彻底删除步骤（供单个和批量共用）"""
    from modules.deploy.services.nfs_service import NFSService
    from modules.deploy.services.k8s_service import K8sService
    from modules.deploy.api.shared import get_k8s_yaml_remote_dir
    
    project = env.project
    project_name = project.name
    env_name = env.name
    env_full = f'{project_name}-{env_name}'
    recycle_info = json.loads(env.recycle_info) if env.recycle_info else {}

    def log(level, message, step=None):
        _write_log(log_file, level, f'{prefix} {message}' if prefix else message, step)

    # 步骤1: 删除本地YAML回收目录
    log('INFO', '删除本地YAML回收目录...')
    yaml_recycle_path = recycle_info.get('yaml_recycle_path')
    try:
        if yaml_recycle_path and os.path.exists(yaml_recycle_path):
            shutil.rmtree(yaml_recycle_path)
            log('OK', f'已删除: {yaml_recycle_path}')
        else:
            log('INFO', '本地YAML回收目录不存在，跳过')
    except Exception as e:
        log('ERROR', f'删除本地YAML失败: {str(e)}')
        raise

    # 步骤2: 删除NFS回收目录
    log('INFO', '删除NFS回收目录...')
    nfs_recycle_dir = recycle_info.get('nfs_recycle_dir')
    try:
        if nfs_recycle_dir:
            nfs = NFSService()
            if nfs.directory_exists(nfs_recycle_dir):
                nfs.remove_directory(nfs_recycle_dir)
                log('OK', f'已删除: {nfs_recycle_dir}')
            else:
                log('INFO', 'NFS回收目录不存在，跳过')
        else:
            log('INFO', '无NFS回收路径记录，跳过')
    except Exception as e:
        log('ERROR', f'删除NFS目录失败: {str(e)}')
        raise

    # 步骤3: 删除远程K8s YAML回收目录
    log('INFO', '删除远程K8s YAML回收目录...')
    k8s_remote_recycle_path = recycle_info.get('k8s_remote_recycle_path')
    try:
        if k8s_remote_recycle_path:
            k8s = K8sService()
            if k8s.remote_directory_exists(k8s_remote_recycle_path):
                k8s.remove_directory(k8s_remote_recycle_path)
                log('OK', f'已删除: {k8s_remote_recycle_path}')
            else:
                log('INFO', '远程YAML回收目录不存在，跳过')
        else:
            log('INFO', '无远程YAML回收路径记录，跳过')
    except Exception as e:
        log('ERROR', f'删除远程YAML回收目录失败: {str(e)}')
        raise

    # 步骤4: 删除远程K8s YAML正式目录
    log('INFO', '删除远程K8s YAML正式目录...')
    try:
        k8s = K8sService()
        remote_yaml_dir = get_k8s_yaml_remote_dir()
        remote_dir = f'{remote_yaml_dir}/{env_full}'
        if k8s.remote_directory_exists(remote_dir):
            k8s.remove_directory(remote_dir)
            log('OK', f'已删除: {remote_dir}')
        else:
            log('INFO', '远程YAML目录不存在，跳过')
    except Exception as e:
        log('ERROR', f'删除远程YAML目录失败: {str(e)}')
        raise

    # 步骤5: 删除K8s Namespace
    log('INFO', '删除K8s Namespace...')
    ns_middleware = f'{env_full}-middleware'
    ns_service = f'{env_full}-service'
    try:
        k8s = K8sService()
        remote_yaml_dir = get_k8s_yaml_remote_dir()
        remote_dir = f'{remote_yaml_dir}/{env_full}'

        def check_and_clean(ns, sub_dirs, label=''):
            r = k8s.exec_command(f'kubectl get pods -n {ns} --no-headers 2>/dev/null | wc -l')
            count = int(r['stdout']) if r['stdout'] and r['stdout'].strip().isdigit() else 0
            if count == 0:
                log('INFO', f'{ns} {label}无残留资源')
                return
            log('WARN', f'{ns} {label}发现{count}个残留Pod，清理中...')
            for sub_dir in sub_dirs:
                r2 = k8s.exec_command(f'ls {remote_dir}/{sub_dir}/ 2>/dev/null')
                if r2['stdout']:
                    for yaml_file in r2['stdout'].split('\n'):
                        yaml_file = yaml_file.strip()
                        if yaml_file.endswith('.yaml') and yaml_file not in ('mysql.yaml', 'public-config.yaml'):
                            k8s.exec_command(f'kubectl delete -f {remote_dir}/{sub_dir}/{yaml_file} --ignore-not-found')
            for attempt in range(6):
                time.sleep(5)
                r4 = k8s.exec_command(f'kubectl get pods -n {ns} --no-headers 2>/dev/null | wc -l')
                c = int(r4['stdout']) if r4['stdout'] and r4['stdout'].strip().isdigit() else 0
                if c == 0:
                    log('OK', f'{ns} {label}资源已清理')
                    return
            log('WARN', f'{ns} 30秒后仍有Pod，强制删除...')
            r5 = k8s.exec_command(f'kubectl get pods -n {ns} --no-headers -o custom-columns=NAME:.metadata.name 2>/dev/null')
            if r5['stdout']:
                for pod in r5['stdout'].split('\n'):
                    pod = pod.strip()
                    if pod:
                        k8s.exec_command(f'kubectl delete pod {pod} -n {ns} --force --grace-period=0')

        check_and_clean(ns_middleware, ['middleware'], '（中间件）')
        check_and_clean(ns_service, ['deployment', 'service'], '（服务）')

        def delete_ns(ns, label=''):
            log('INFO', f'删除Namespace: {ns} {label}...')
            k8s.exec_command(f'kubectl delete namespace {ns} --ignore-not-found --timeout=30s', timeout=40)
            r2 = k8s.exec_command(f'kubectl get namespace {ns} -o name 2>/dev/null')
            if r2['stdout'] and f'namespace/{ns}' in r2['stdout']:
                log('WARN', f'{ns} 未删除，强制清理finalizer...')
                r3 = k8s.exec_command(
                    f"kubectl get namespace {ns} -o json | "
                    f"sed 's/\"finalizers\": \\[[^]]*\\]/\"finalizers\": []/' | "
                    f"kubectl replace --raw \"/api/v1/namespaces/{ns}/finalize\" -f -"
                )
                if r3['exit_code'] == 0:
                    log('OK', f'已强制删除: {ns}')
                else:
                    log('WARN', f'强制删除失败: {ns} - {r3["stderr"]}')
            else:
                log('OK', f'已删除: {ns}')

        delete_ns(ns_middleware, '（含PVC）')
        delete_ns(ns_service)
    except Exception as e:
        log('ERROR', f'删除K8s Namespace失败: {str(e)}')
        raise

    # 步骤6: Nginx配置清理（删除回收站文件）
    log('INFO', 'Nginx配置清理...')
    try:
        domain = env.domain or ''
        if domain:
            _delete_nginx_config_recycle(recycle_info.get('nginx_conf'), domain, log)
        else:
            log('INFO', '环境无域名记录，跳过Nginx清理')
    except Exception as e:
        log('ERROR', f'Nginx配置清理失败: {str(e)}')
        raise

    # 步骤7: 清理关联记录（构建记录/调度日志）
    log('INFO', '清理关联记录（构建记录/调度日志）...')
    try:
        from modules.cicd.models import Build, ScheduleLog
        build_ids = [b.id for b in db.session.query(Build.id).filter_by(environment_id=env.id).all()]
        if build_ids:
            sch_count = ScheduleLog.query.filter(ScheduleLog.build_id.in_(build_ids)).delete(synchronize_session=False)
            bld_count = Build.query.filter(Build.id.in_(build_ids)).delete(synchronize_session=False)
            db.session.commit()
            log('OK', f'已清理: 构建记录{bld_count}条, 调度日志{sch_count}条')
        else:
            log('INFO', '无构建记录，跳过')
    except Exception as e:
        db.session.rollback()
        log('ERROR', f'清理关联记录失败: {str(e)}')
        raise

    # 步骤8: 删除数据库记录
    log('INFO', '删除数据库记录...')
    try:
        db.session.delete(env)
        db.session.commit()
        log('OK', '数据库记录已删除')
    except Exception as e:
        db.session.rollback()
        log('ERROR', f'删除数据库记录失败: {str(e)}')
        raise


def _run_deploy_task(app, task_key, data):
    """后台线程：执行部署并写入日志文件"""
    with app.app_context():
        from modules.deploy.services.yaml_generator import YAMLGenerator
        from modules.deploy.services.nfs_service import NFSService
        from modules.deploy.services.k8s_service import K8sService
        from modules.deploy.api.shared import get_k8s_yaml_remote_dir
        
        action = data.get('action', 'create_env')

        # 新增服务走精简流程（只处理该服务，不重复环境级步骤）
        if action == 'create_service':
            _run_create_service_task(app, task_key, data)
            return

        action_type_map = {'create_project': 'project', 'create_env': 'environment', 'create_service': 'service'}
        log_type = action_type_map.get(action, 'environment')

        # 确定项目名和环境名
        if action == 'create_project':
            project_name = data.get('project_name', '').strip()
            env_name = data.get('env_name', '').strip()
        elif action == 'create_env':
            project_id = data.get('project_id')
            project = Project.query.get(project_id) if project_id else None
            project_name = project.name if project else 'unknown'
            env_name = data.get('env_name', '').strip()
        else:
            project_name = data.get('project_name', 'unknown')
            env_name = data.get('env_name', '').strip()

        log_file = _get_log_path(project_name, env_name, log_type)

        def log(level, message, step=None):
            _write_log(log_file, level, message, step)

        with _tasks_lock:
            _deploy_tasks[task_key] = {
                'status': 'running',
                'log_file': log_file,
                'started_at': datetime.now().isoformat(),
                'project_name': project_name,
                'env_name': env_name
            }

        success_count = 0
        fail_count = 0
        total_steps = 9

        try:
            # ── 步骤1: 保存配置到数据库 ──
            log('INFO', '保存配置到数据库...', step=f'步骤1/{total_steps}')
            log('INFO', f'  项目名称: {project_name}')
            log('INFO', f'  环境名称: {env_name}')
            log('INFO', f'  域名: {data.get("domain", "")}')
            log('INFO', f'  调试端口起始: {data.get("debug_port", 30000)}')
            log('INFO', f'  源环境: {data.get("source_env", "无")}')

            # nacos_namespace 获取逻辑
            if not data.get('nacos_namespace'):
                if action == 'create_project':
                    # 新增项目：从系统设置读取默认值
                    default_ns = Setting.query.filter_by(key='default_nacos_namespace').first()
                    if default_ns and default_ns.value:
                        data['nacos_namespace'] = default_ns.value
                        log('INFO', f'  从系统设置读取 nacos_namespace: {data["nacos_namespace"]}')
                elif data.get('source_env'):
                    # 新增环境/服务：从源环境继承
                    source_env_name = data.get('source_env')
                    source_env = Environment.query.join(Project).filter(
                        Project.name == project_name,
                        Environment.name == source_env_name
                    ).first()
                    if source_env:
                        data['nacos_namespace'] = source_env.nacos_namespace or ''
                        data['seata_nacos_namespace'] = source_env.seata_nacos_namespace or ''
                        log('INFO', f'  从源环境继承 nacos_namespace: {data.get("nacos_namespace", "")}')
            log('INFO', f'  Nacos命名空间: {data.get("nacos_namespace", "")}')

            services_list = data.get('services', [])
            svc_names = [s.get('name', s.get('app_name', '')) if isinstance(s, dict) else str(s) for s in services_list[:5]]
            log('INFO', f'  服务列表: {len(services_list)}个 - {svc_names}{"..." if len(services_list) > 5 else ""}')
            middleware_list = data.get('middleware', [])
            mw_names = [m.get('name', m.get('type', '')) if isinstance(m, dict) else str(m) for m in middleware_list]
            log('INFO', f'  中间件: {len(middleware_list)}个 - {mw_names}')
            try:
                if action == 'create_project':
                    _save_project_config(data, log)
                elif action == 'create_env':
                    _save_env_config(data, log)
                else:
                    _save_env_config(data, log)
                success_count += 1
                log('OK', '配置保存成功')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'配置保存失败: {str(e)}')
                log('FAILED', f'部署中止，配置保存失败')
                with _tasks_lock:
                    _deploy_tasks[task_key]['status'] = 'failed'
                return

            # ── 步骤2: 生成YAML文件 ──
            log('INFO', '生成YAML文件...', step=f'步骤2/{total_steps}')
            try:
                # 检查远程目录是否已存在
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{project_name}-{env_name}"
                if k8s.remote_directory_exists(remote_dir):
                    log('ERROR', f'远程目录已存在: {remote_dir}，部署终止')
                    fail_count += 1
                    log('FAILED', '部署中止，远程目录已存在')
                    with _tasks_lock:
                        _deploy_tasks[task_key]['status'] = 'failed'
                    return

                generator = YAMLGenerator()

                if action == 'create_project':
                    yaml_content = generator.generate_all(data, data.get('services', []))
                else:
                    project_config = _build_project_config(project_name, env_name, data)
                    yaml_content = generator.generate_all(project_config, data.get('services', []))

                output_setting = Setting.query.filter_by(key='yaml_output_dir').first()
                output_dir = output_setting.value if output_setting else './output'
                saved_path = generator.save_to_files(output_dir, yaml_content)

                # 列出生成的YAML目录和文件
                if os.path.isdir(saved_path):
                    sub_items = [d for d in os.listdir(saved_path) if os.path.isdir(os.path.join(saved_path, d))]
                    log('INFO', f'  输出目录: {saved_path}')
                    for sub in sorted(sub_items):
                        sub_path = os.path.join(saved_path, sub)
                        file_count = len([f for f in os.listdir(sub_path) if f.endswith(('.yaml', '.yml'))])
                        log('INFO', f'  子目录: {sub}/ ({file_count}个YAML文件)')

                # 上传到K8s Master
                k8s.upload_directory(saved_path, remote_dir)
                log('OK', f'YAML已上传到K8s Master: {remote_dir}')

                success_count += 1
                log('OK', f'YAML文件已生成: {saved_path}')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'YAML生成失败: {str(e)}')

            # ── 步骤3: 创建NFS目录 ──
            log('INFO', '创建NFS目录...', step=f'步骤3/{total_steps}')
            try:
                nfs = NFSService()
                services_list = data.get('services', [])
                from modules.system.settings_service import get_setting
                log('INFO', f'  挂载点: logs={get_setting("nfs_logs_mount")}, data={get_setting("nfs_data_mount")}, datastorg={get_setting("nfs_datastorg_mount")}')
                nfs_result = nfs.create_project_dirs(project_name, env_name, services_list)
                created = nfs_result.get('created', 0)
                skipped = nfs_result.get('skipped', 0)
                failed = nfs_result.get('failed', 0)

                # 打印创建的目录
                for item in nfs_result.get('dirs', []):
                    log('INFO', f'  已创建: {item.get("path", "")} ({item.get("type", "")})')
                for item in nfs_result.get('skipped_dirs', []):
                    log('INFO', f'  已存在: {item.get("path", "")} ({item.get("type", "")})')
                for item in nfs_result.get('errors', []):
                    log('ERROR', f'  失败: {item.get("path", "")} - {item.get("error", "")}')

                if failed > 0:
                    log('WARN', f'NFS目录创建完成: {created}成功, {skipped}跳过, {failed}失败')
                else:
                    log('OK', f'NFS目录创建完成: {created}成功, {skipped}跳过')
                success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'NFS目录创建失败: {str(e)}')

            # ── 步骤4: 复制 Nacos 数据（如有source_env） ──
            source_env = data.get('source_env', '')
            log('INFO', f'复制Nacos数据（源环境: {source_env}）...' if source_env else '无数据复制需求，跳过',
                step=f'步骤4/{total_steps}')
            if source_env:
                try:
                    nfs = NFSService()
                    log('INFO', f'  源: {project_name}-{source_env} -> 目标: {project_name}-{env_name}')
                    copy_result = nfs.copy_project_dirs(project_name, source_env, project_name, env_name,
                                                         data.get('services', []))
                    copied = copy_result.get('copied', 0)
                    failed = copy_result.get('failed', 0)

                    # 打印复制的目录详情
                    for item in copy_result.get('dirs', []):
                        desc = item.get('desc', item.get('type', ''))
                        src = item.get('source', '')
                        dst = item.get('dest', '')
                        log('INFO', f'  已复制: {src} -> {dst} ({desc})')
                    for item in copy_result.get('errors', []):
                        log('ERROR', f'  复制失败: {item.get("source", item.get("desc", ""))} - {item.get("error", "")}')

                    if failed > 0:
                        log('WARN', f'数据复制完成: {copied}个目录成功, {failed}个失败')
                    else:
                        log('OK', f'数据复制完成: {copied}个目录')
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    log('ERROR', f'数据复制失败: {str(e)}')
            else:
                success_count += 1

            # ── 步骤5: 创建Harbor项目 + 保留策略 ──
            log('INFO', '创建Harbor项目...', step=f'步骤5/{total_steps}')
            try:
                harbor_result = _create_harbor_project_step(project_name, env_name, log=log)
                if harbor_result.get('status') != 'failed':
                    success_count += 1
                    log('OK', f'Harbor项目就绪: {harbor_result.get("status")}')
                else:
                    fail_count += 1
                    log('WARN', f'Harbor项目创建失败: {harbor_result.get("error")}')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Harbor项目创建异常: {str(e)}')

            # ── 步骤6: K8s创建Namespace ──
            log('INFO', 'K8s创建Namespace...', step=f'步骤6/{total_steps}')
            ns_middleware = f"{project_name}-{env_name}-middleware"
            ns_service = f"{project_name}-{env_name}-service"
            log('INFO', f'  中间件Namespace: {ns_middleware}')
            log('INFO', f'  服务Namespace: {ns_service}')
            try:
                k8s = K8sService()
                # 创建中间件 namespace
                r1 = k8s.exec_command(f'kubectl create namespace {ns_middleware}')
                if r1['exit_code'] == 0:
                    log('OK', f'  Namespace已创建: {ns_middleware}')
                elif 'already exists' in r1['stderr']:
                    log('INFO', f'  Namespace已存在: {ns_middleware}')
                else:
                    raise Exception(r1['stderr'] or r1['stdout'])

                # 创建服务 namespace
                r2 = k8s.exec_command(f'kubectl create namespace {ns_service}')
                if r2['exit_code'] == 0:
                    log('OK', f'  Namespace已创建: {ns_service}')
                elif 'already exists' in r2['stderr']:
                    log('INFO', f'  Namespace已存在: {ns_service}')
                else:
                    raise Exception(r2['stderr'] or r2['stdout'])

                success_count += 1
                log('OK', f'Namespace创建完成: {ns_middleware}, {ns_service}')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Namespace创建失败: {str(e)}')

            # ── 步骤7: 启动中间件 ──
            log('INFO', '启动中间件...', step=f'步骤7/{total_steps}')
            try:
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{project_name}-{env_name}"
                middleware_dir = f"{remote_dir}/middleware"

                # 7.1 先应用 public-config.yaml（YAML内嵌namespace，直接apply）
                log('INFO', '应用公共配置...')
                public_config = f"{remote_dir}/public-config.yaml"
                r = k8s.exec_command(f'test -f {public_config} && echo EXISTS')
                if r['stdout'] == 'EXISTS':
                    # YAML中已内嵌namespace(xxx-service)，直接apply，不用-n覆盖
                    r2 = k8s.exec_command(f'kubectl apply -f {public_config}')
                    if r2['exit_code'] == 0:
                        log('OK', f'  public-config.yaml 已应用')
                    else:
                        log('WARN', f'  public-config应用失败: {r2["stderr"]}')
                    # 同时应用到middleware namespace（去掉YAML中的namespace字段，用-n指定）
                    r3 = k8s.exec_command(
                        f"cat {public_config} | sed '/^  namespace:/d' | kubectl apply -n {ns_middleware} -f -"
                    )
                    if r3['exit_code'] == 0:
                        log('OK', f'  public-config.yaml -> {ns_middleware}')
                    else:
                        log('WARN', f'  public-config应用到{ns_middleware}失败: {r3["stderr"]}')
                else:
                    log('INFO', f'  public-config.yaml不存在，跳过')

                # 7.2 按依赖顺序应用中间件YAML
                log('INFO', '应用中间件YAML...')
                # 按顺序：mysql-nfs(Nacos依赖) → mysql → nacos → rabbitmq → redis
                middleware_order = ['mysql-nfs.yaml', 'mysql.yaml', 'nacos.yaml', 'rabbitmq.yaml', 'redis.yaml']
                applied_mw = []
                skipped_mw = []
                for mw_file in middleware_order:
                    r = k8s.exec_command(f'test -f {middleware_dir}/{mw_file} && echo EXISTS')
                    if r['stdout'] == 'EXISTS':
                        r2 = k8s.exec_command(f'kubectl apply -f {middleware_dir}/{mw_file}', timeout=60)
                        if r2['exit_code'] == 0:
                            log('OK', f'  已应用: {mw_file}')
                            applied_mw.append(mw_file)
                        else:
                            log('ERROR', f'  应用失败: {mw_file} - {r2["stderr"]}')
                    else:
                        skipped_mw.append(mw_file)
                        log('INFO', f'  跳过（文件不存在）: {mw_file}')
                if skipped_mw:
                    log('INFO', f'  已跳过 {len(skipped_mw)} 个: {skipped_mw}')
                log('INFO', f'  中间件YAML应用完成: {len(applied_mw)}个已应用')

                # 7.3 等待所有中间件Pod就绪
                log('INFO', '等待中间件Pod就绪（最长5分钟）...')
                import time
                ready = False
                for attempt in range(30):  # 30次 × 10秒 = 300秒
                    time.sleep(10)
                    r = k8s.exec_command(
                        f'kubectl get pods -n {ns_middleware} '
                        f'-o jsonpath=\'{{.items[*].status.phase}}\''
                    )
                    phases = r['stdout'].split() if r['stdout'] else []
                    if phases and all(p in ('Running', 'Succeeded') for p in phases):
                        log('OK', f'  所有中间件Pod已就绪（尝试{attempt+1}/30，状态: {phases}）')
                        ready = True
                        break
                    # 显示当前状态
                    r2 = k8s.exec_command(
                        f'kubectl get pods -n {ns_middleware} '
                        f'-o jsonpath=\'{{range .items[*]}}{{.metadata.name}}={{.status.phase}} {{end}}\''
                    )
                    log('INFO', f'  等待中（尝试{attempt+1}/30）: {r2["stdout"]}')

                if not ready:
                    # 最终状态快照
                    r = k8s.exec_command(
                        f'kubectl get pods -n {ns_middleware} '
                        f'-o jsonpath=\'{{range .items[*]}}{{.metadata.name}}={{.status.phase}} {{end}}\''
                    )
                    if r['stdout']:
                        for pod_status in r['stdout'].strip().split():
                            log('WARN', f'  {pod_status}')

                # 7.4 MySQL数据复制（仅复制模式，有source_env时）
                source_env = data.get('source_env', '')
                if source_env:
                    log('INFO', 'MySQL数据复制...')
                    log('INFO', f'  停止MySQL: {ns_middleware}/mysql-0')
                    # 停止MySQL StatefulSet
                    r = k8s.exec_command(
                        f'kubectl scale statefulset mysql --replicas=0 -n {ns_middleware}'
                    )
                    if r['exit_code'] == 0:
                        log('OK', f'  MySQL已停止（exit_code=0）')
                    else:
                        log('WARN', f'  停止MySQL: {r["stderr"] or r["stdout"]}')

                    # 等待MySQL Pod完全终止
                    log('INFO', '  等待MySQL Pod终止...')
                    for attempt in range(30):
                        time.sleep(5)
                        r = k8s.exec_command(
                            f'kubectl get pod mysql-0 -n {ns_middleware} '
                            f'-o jsonpath=\'{{.status.phase}}\' 2>/dev/null'
                        )
                        if not r['stdout'] or r['exit_code'] != 0:
                            log('OK', f'  MySQL Pod已终止（尝试{attempt+1}/30）')
                            break
                        log('INFO', f'  MySQL状态: {r["stdout"]}（尝试{attempt+1}/30）')

                    # 通过NFS复制MySQL PVC数据
                    log('INFO', f'  复制MySQL PVC数据（源: {project_name}-{source_env} -> {project_name}-{env_name}）...')
                    try:
                        nfs = NFSService()
                        sync_result = nfs.sync_mysql_pvc_data(
                            project_name, source_env,
                            project_name, env_name
                        )
                        if sync_result.get('success'):
                            log('OK', f'  MySQL PVC数据复制成功: {sync_result.get("copied_files", 0)}个文件/目录')
                            log('INFO', f'  源PVC: {sync_result.get("source_pvc", "")}')
                            log('INFO', f'  目标PVC: {sync_result.get("dest_pvc", "")}')
                        else:
                            log('WARN', f'  MySQL PVC数据复制: {sync_result.get("message", "未知原因")}')
                    except Exception as e:
                        log('WARN', f'  MySQL PVC数据复制异常: {str(e)}')

                    # 重新启动MySQL
                    log('INFO', '  重新启动MySQL...')
                    r = k8s.exec_command(
                        f'kubectl scale statefulset mysql --replicas=1 -n {ns_middleware}'
                    )
                    if r['exit_code'] == 0:
                        log('OK', '  MySQL已启动（replicas=1）')
                    else:
                        log('WARN', f'  启动MySQL: {r["stderr"] or r["stdout"]}')

                    # 等待MySQL启动就绪
                    log('INFO', '  等待MySQL启动就绪...')
                    for attempt in range(24):
                        time.sleep(10)
                        r = k8s.exec_command(
                            f'kubectl get pod mysql-0 -n {ns_middleware} '
                            f'-o jsonpath=\'{{.status.phase}}\''
                        )
                        if r['stdout'] == 'Running':
                            log('OK', f'  MySQL Pod已Running（尝试{attempt+1}/24）')
                            break
                        log('INFO', f'  MySQL状态: {r["stdout"]}（尝试{attempt+1}/24）')
                else:
                    log('INFO', '新建模式，跳过MySQL数据复制')

                # 7.5 最终健康检查
                log('INFO', '中间件最终健康检查...')
                r = k8s.exec_command(
                    f'kubectl get pods -n {ns_middleware} '
                    f'-o jsonpath=\'{{range .items[*]}}{{.metadata.name}}={{.status.phase}} {{end}}\''
                )
                if r['stdout']:
                    for pod_status in r['stdout'].strip().split():
                        log('INFO', f'  {pod_status}')
                success_count += 1
                log('OK', '中间件启动流程完成')

            except Exception as e:
                fail_count += 1
                log('ERROR', f'中间件启动失败: {str(e)}')
                import traceback
                log('ERROR', traceback.format_exc())

            # ── 步骤8: 应用Service ──
            log('INFO', '应用Service...', step=f'步骤8/{total_steps}')
            try:
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{project_name}-{env_name}"
                service_dir = f"{remote_dir}/service"

                r = k8s.exec_command(f'test -d {service_dir} && echo EXISTS')
                if r['stdout'] == 'EXISTS':
                    r2 = k8s.exec_command(f'kubectl apply -f {service_dir}/', timeout=60)
                    if r2['exit_code'] == 0:
                        files = k8s.list_remote_files(service_dir)
                        log('OK', f'  Service已应用（{len(files)}个文件）')
                        for f in files:
                            log('INFO', f'  已应用: {f}')
                        success_count += 1
                    else:
                        raise Exception(r2['stderr'] or 'apply 失败')
                else:
                    log('WARN', f'  Service目录不存在: {service_dir}，跳过')
                    success_count += 1

            except Exception as e:
                fail_count += 1
                log('ERROR', f'Service应用失败: {str(e)}')

            # ── 步骤9: 生成Nginx配置 ──
            if action != 'create_service':
                log('INFO', '生成Nginx配置文件...', step=f'步骤9/{total_steps}')
                try:
                    _generate_nginx_config(project_name, env_name, data, log)
                    success_count += 1
                    log('OK', 'Nginx配置生成完成')
                except Exception as e:
                    fail_count += 1
                    log('ERROR', f'Nginx配置生成失败: {str(e)}')
            else:
                log('INFO', '新增服务不生成Nginx配置，跳过', step=f'步骤9/{total_steps}')

            # ── 完成 ──
            elapsed = (datetime.now() - datetime.strptime(
                _deploy_tasks.get(task_key, {}).get('started_at', datetime.now().isoformat())[:19],
                '%Y-%m-%dT%H:%M:%S'
            )).total_seconds()
            if fail_count == 0:
                log('DONE', f'部署完成，共{total_steps}步，全部成功，耗时{elapsed:.1f}秒')
                status = 'completed'
            else:
                log('DONE', f'部署完成，共{total_steps}步，成功{success_count}，失败{fail_count}，耗时{elapsed:.1f}秒')
                status = 'completed'  # 部分失败也算完成

            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = status

        except Exception as e:
            log('FAILED', f'部署异常终止: {str(e)}')
            import traceback
            log('ERROR', traceback.format_exc())
            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'failed'


def _run_create_service_task(app, task_key, data):
    """后台线程：往已有环境新增服务（精简流程，只处理该服务本身）

    步骤：
      1. 校验并保存配置（追加到已有环境 deploy_config.services，不覆盖已有服务）
      2. 生成该服务的 deployment/service YAML，增量上传到远程（不影响环境其他文件）
      3. 创建该服务的 NFS 目录
      4. kubectl apply 该服务的 service（deployment 不应用：新增服务未触发 CI/CD，镜像尚不存在，
         待 CI 构建成功后由自动部署再 apply deployment）
    """
    with app.app_context():
        import tempfile as _tempfile
        from modules.deploy.services.yaml_generator import YAMLGenerator
        from modules.deploy.services.nfs_service import NFSService
        from modules.deploy.services.k8s_service import K8sService
        from modules.deploy.api.shared import get_k8s_yaml_remote_dir

        # 解析环境（execute_deploy 已回填 data，线程内再兜底解析一次）
        env_id = data.get('environment_id')
        env = Environment.query.get(env_id) if env_id else None
        if not env or env.is_deleted or not env.project:
            with _tasks_lock:
                _deploy_tasks[task_key] = {
                    'status': 'failed',
                    'log_file': None,
                    'started_at': datetime.now().isoformat(),
                    'project_name': data.get('project_name', 'unknown'),
                    'env_name': data.get('env_name', 'unknown')
                }
            return
        project = env.project
        project_name = project.name
        env_name = env.name

        # 服务参数（前端 create_service 每次提交一个服务）
        services = data.get('services') or []
        if not services:
            with _tasks_lock:
                _deploy_tasks[task_key] = {
                    'status': 'failed',
                    'log_file': None,
                    'started_at': datetime.now().isoformat(),
                    'project_name': project_name,
                    'env_name': env_name
                }
            return
        raw_svc = services[0]
        service = dict(raw_svc) if isinstance(raw_svc, dict) else {'name': str(raw_svc)}
        svc_name = str(service.get('name', service.get('app_name', ''))).strip()
        if not svc_name:
            with _tasks_lock:
                _deploy_tasks[task_key] = {
                    'status': 'failed',
                    'log_file': None,
                    'started_at': datetime.now().isoformat(),
                    'project_name': project_name,
                    'env_name': env_name
                }
            return

        log_file = _get_log_path(project_name, env_name, 'service')

        def log(level, message, step=None):
            _write_log(log_file, level, message, step)

        with _tasks_lock:
            _deploy_tasks[task_key] = {
                'status': 'running',
                'log_file': log_file,
                'started_at': datetime.now().isoformat(),
                'project_name': project_name,
                'env_name': env_name
            }

        def _rollback_service():
            """失败时回滚：从 deploy_config.services 移除刚追加的服务，避免半完成态"""
            try:
                db.session.rollback()  # 先清理可能挂起的事务，再重新读取
                fresh = Environment.query.get(env.id)
                if fresh and fresh.deploy_config:
                    cfg = json.loads(fresh.deploy_config)
                    if isinstance(cfg, dict):
                        cfg['services'] = [
                            s for s in cfg.get('services', [])
                            if not ((s.get('name', s.get('app_name', '')) if isinstance(s, dict) else str(s)) == svc_name)
                        ]
                        fresh.deploy_config = json.dumps(cfg, ensure_ascii=False)
                        db.session.commit()
            except Exception:
                db.session.rollback()

        success_count = 0
        fail_count = 0
        total_steps = 4
        svc_index = 0

        try:
            # ── 步骤1: 校验并保存配置到数据库 ──
            log('INFO', '校验并保存服务配置...', step=f'步骤1/{total_steps}')
            log('INFO', f'  项目: {project_name}')
            log('INFO', f'  环境: {env_name}')
            log('INFO', f'  服务: {svc_name} (xms={service.get("xms", 2)}G, xmx={service.get("xmx", 8)}G, replicas={service.get("replicas", 1)})')
            try:
                svc_index = _save_service_config(env, service, svc_name)
                success_count += 1
                log('OK', '配置保存成功（已追加到环境服务列表）')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'配置保存失败: {str(e)}')
                log('FAILED', '部署中止，配置保存失败')
                with _tasks_lock:
                    _deploy_tasks[task_key]['status'] = 'failed'
                return

            # ── 步骤2: 生成并上传YAML ──
            log('INFO', '生成服务YAML...', step=f'步骤2/{total_steps}')
            try:
                project_config = _build_service_project_config(env, project_name, env_name)
                generator = YAMLGenerator()
                service['index'] = svc_index  # 端口偏移 = 已有服务数
                yaml_content = {
                    'project_name': project_name,
                    'env_name': env_name,
                    'deployments': [{
                        'name': f"{project_name}-{svc_name}",
                        'yaml': generator.generate_deployment(project_name, env_name, service, project_config)
                    }],
                    'services': [{
                        'name': f"{project_name}-{svc_name}",
                        'yaml': generator.generate_service(project_name, env_name, service, project_config)
                    }],
                    'public_config': None,
                    'middleware': [],
                }
                output_setting = Setting.query.filter_by(key='yaml_output_dir').first()
                output_dir = output_setting.value if output_setting else './output'
                saved_path = generator.save_to_files(output_dir, yaml_content)
                log('INFO', f'  本地: {saved_path}/deployment/{project_name}-{svc_name}.yaml')
                log('INFO', f'  本地: {saved_path}/service/{project_name}-{svc_name}.yaml')

                # 只上传新服务的两个文件（增量补到已有远程目录，不动环境其他文件）
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{project_name}-{env_name}"
                tmp_dir = _tempfile.mkdtemp(prefix='svc_upload_')
                try:
                    for sub in ('deployment', 'service'):
                        os.makedirs(os.path.join(tmp_dir, sub), exist_ok=True)
                        shutil.copy(
                            os.path.join(saved_path, sub, f"{project_name}-{svc_name}.yaml"),
                            os.path.join(tmp_dir, sub, f"{project_name}-{svc_name}.yaml")
                        )
                    k8s = K8sService()
                    k8s.upload_directory(tmp_dir, remote_dir)
                    log('OK', f'  已上传: {remote_dir}/deployment|service/{project_name}-{svc_name}.yaml')
                finally:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                success_count += 1
                log('OK', '服务YAML生成并上传完成')
                log('INFO', '  deployment 文件仅生成留存，供后续 CI 构建成功后自动部署使用')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'YAML生成失败: {str(e)}')
                _rollback_service()
                log('INFO', '已回滚数据库服务配置，可修正后重新提交')
                log('FAILED', '部署中止，YAML生成失败')
                with _tasks_lock:
                    _deploy_tasks[task_key]['status'] = 'failed'
                return

            # ── 步骤3: 创建NFS目录 ──
            log('INFO', '创建NFS目录...', step=f'步骤3/{total_steps}')
            try:
                nfs = NFSService()
                nfs_result = nfs.create_project_dirs(project_name, env_name, [service])
                created = nfs_result.get('created', 0)
                skipped = nfs_result.get('skipped', 0)
                failed = nfs_result.get('failed', 0)
                for item in nfs_result.get('dirs', []):
                    log('INFO', f'  已创建: {item.get("path", "")} ({item.get("type", "")})')
                for item in nfs_result.get('errors', []):
                    log('ERROR', f'  失败: {item.get("path", "")} - {item.get("error", "")}')
                if failed > 0:
                    log('WARN', f'NFS目录创建: {created}成功, {skipped}跳过, {failed}失败')
                else:
                    log('OK', f'NFS目录创建: {created}成功, {skipped}跳过')
                success_count += 1
            except Exception as e:
                fail_count += 1
                log('ERROR', f'NFS目录创建失败: {str(e)}')

            # ── 步骤4: 应用 Service 到 K8s ──
            # 只应用 service：新增服务未触发 CI/CD 构建，镜像尚不存在，
            # deployment 一 apply 就会 ImagePullBackOff；待 CI 构建成功后自动部署再 apply deployment
            log('INFO', '应用Service到K8s...', step=f'步骤4/{total_steps}')
            log('INFO', '  跳过Deployment应用（无镜像，待CI构建后自动部署再应用）')
            try:
                k8s = K8sService()
                remote_yaml_dir = get_k8s_yaml_remote_dir()
                remote_dir = f"{remote_yaml_dir}/{project_name}-{env_name}"
                r2 = k8s.exec_command(
                    f'kubectl apply -f {remote_dir}/service/{project_name}-{svc_name}.yaml', timeout=60)
                if r2['exit_code'] != 0:
                    raise Exception(r2['stderr'] or r2['stdout'])
                log('OK', f'  Service已应用: {project_name}-{svc_name}')
                success_count += 1
                log('OK', 'Service应用完成')
            except Exception as e:
                fail_count += 1
                log('ERROR', f'Service应用失败: {str(e)}')

            # ── 完成 ──
            if fail_count == 0:
                log('DONE', f'新增服务完成，共{total_steps}步，全部成功')
            else:
                # 部分失败：回滚数据库配置，避免「DB有记录但K8s未部署」的半完成态
                _rollback_service()
                log('WARN', '存在失败步骤，已回滚数据库服务配置（可修正后重新提交）')
                log('DONE', f'新增服务完成，共{total_steps}步，成功{success_count}，失败{fail_count}')

            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'completed'

        except Exception as e:
            _rollback_service()
            log('FAILED', f'新增服务异常终止: {str(e)}')
            import traceback
            log('ERROR', traceback.format_exc())
            with _tasks_lock:
                _deploy_tasks[task_key]['status'] = 'failed'


def _save_service_config(env, service, svc_name):
    """保存新增服务：读取已有环境 deploy_config，追加服务后更新（不覆盖已有服务）

    Returns:
        int: 新服务在服务列表中的 index（作为端口偏移）
    """
    config = {}
    if env.deploy_config:
        try:
            config = json.loads(env.deploy_config)
        except Exception:
            config = {}
    if not isinstance(config, dict):
        config = {}

    services = config.get('services') or []
    for s in services:
        sname = s.get('name', s.get('app_name', '')) if isinstance(s, dict) else str(s)
        if sname == svc_name:
            raise Exception(f'服务已存在: {svc_name}')

    def _to_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    new_svc = {
        'name': svc_name,
        'xms': _to_int(service.get('xms'), 2),
        'xmx': _to_int(service.get('xmx'), 8),
        'replicas': _to_int(service.get('replicas'), 1),
    }
    index = len(services)
    services.append(new_svc)
    config['services'] = services
    env.deploy_config = json.dumps(config, ensure_ascii=False)
    db.session.commit()
    return index


def _build_service_project_config(env, project_name, env_name):
    """从已有环境构建项目配置（供新增服务生成 YAML 使用）

    继承环境已存的端口/域名/公共配置，而不是前端 data（create_service 不传这些）。
    """
    cfg = {}
    if env.deploy_config:
        try:
            cfg = json.loads(env.deploy_config)
        except Exception:
            cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    common = _get_common_settings()

    default_port = env.port_start or 30000
    return {
        'project_name': project_name,
        'env_name': env_name,
        'tag': cfg.get('tag') or datetime.now().strftime('%Y%m%d%H%M'),
        'nacos_namespace': env.nacos_namespace or cfg.get('nacos_namespace', ''),
        'seata_nacos_namespace': env.seata_nacos_namespace or cfg.get('seata_nacos_namespace', ''),
        'domain': env.domain or cfg.get('domain', ''),
        'debug_port': cfg.get('debug_port', default_port),
        'node_port': cfg.get('node_port', default_port + 30),
        'jmx_port': cfg.get('jmx_port', default_port + 60),
        'middleware_port': cfg.get('middleware_port', default_port + 90),
        'publicurl': cfg.get('publicurl') or common.get('publicurl', ''),
        'privateurl': cfg.get('privateurl') or common.get('privateurl', ''),
        'publicbucket': cfg.get('publicbucket') or common.get('publicbucket', ''),
        'privatebucket': cfg.get('privatebucket') or common.get('privatebucket', ''),
        'ossak': cfg.get('ossak') or common.get('ossak', ''),
        'osssk': cfg.get('osssk') or common.get('osssk', ''),
        'encrypted': cfg.get('encrypted') or common.get('encrypted', ''),
        'riskKey': cfg.get('riskKey') or common.get('riskKey', ''),
        'es_pass': cfg.get('es_pass') or common.get('es_pass', ''),
    }


# ─── 配置保存/构建 ────────────────────────────────────────

def _save_project_config(data, log):
    """保存项目+环境配置到数据库"""
    project_name = data.get('project_name', '').strip()
    env_name = data.get('env_name', '').strip()

    project = Project.query.filter_by(name=project_name).first()
    if not project:
        project = Project(name=project_name, description=data.get('project_desc', ''))
        db.session.add(project)
        db.session.flush()
    elif data.get('project_desc'):
        project.description = data['project_desc']

    existing_env = Environment.query.filter_by(project_id=project.id, name=env_name).first()
    if existing_env:
        db.session.delete(existing_env)
        db.session.flush()

    deploy_config = _build_deploy_config(data)
    env = Environment(
        project_id=project.id,
        name=env_name,
        domain=data.get('domain', ''),
        port_start=data.get('debug_port', 30000),
        nacos_namespace=data.get('nacos_namespace', ''),
        seata_nacos_namespace=data.get('seata_nacos_namespace', ''),
        deploy_config=json.dumps(deploy_config, ensure_ascii=False)
    )
    db.session.add(env)
    db.session.commit()


def _save_env_config(data, log):
    """保存环境配置到数据库"""
    project_id = data.get('project_id')
    project = Project.query.get(project_id) if project_id else None
    if not project:
        raise Exception('项目不存在')

    name = data.get('env_name', '').strip()
    existing_env = Environment.query.filter_by(project_id=project.id, name=name).first()
    if existing_env:
        db.session.delete(existing_env)
        db.session.flush()

    deploy_config = _build_deploy_config(data)
    env = Environment(
        project_id=project.id,
        name=name,
        domain=data.get('domain', ''),
        port_start=data.get('debug_port', 30000),
        nacos_namespace=data.get('nacos_namespace', ''),
        seata_nacos_namespace=data.get('seata_nacos_namespace', ''),
        deploy_config=json.dumps(deploy_config, ensure_ascii=False)
    )
    db.session.add(env)
    db.session.commit()


def _build_project_config(project_name, env_name, data):
    """构建项目配置字典"""
    # 从系统设置读取公共配置（如果data中没有提供）
    common = _get_common_settings()

    return {
        'project_name': project_name,
        'env_name': env_name,
        'tag': datetime.now().strftime('%Y%m%d%H%M'),
        'nacos_namespace': data.get('nacos_namespace', ''),
        'domain': data.get('domain', ''),
        'debug_port': data.get('debug_port', 30000),
        'node_port': data.get('node_port', 30030),
        'jmx_port': data.get('jmx_port', 30060),
        'middleware_port': data.get('middleware_port', 30090),
        'publicurl': data.get('publicurl') or common.get('publicurl', ''),
        'privateurl': data.get('privateurl') or common.get('privateurl', ''),
        'publicbucket': data.get('publicbucket') or common.get('publicbucket', ''),
        'privatebucket': data.get('privatebucket') or common.get('privatebucket', ''),
        'ossak': data.get('ossak') or common.get('ossak', ''),
        'osssk': data.get('osssk') or common.get('osssk', ''),
        'encrypted': data.get('encrypted') or common.get('encrypted', ''),
        'riskKey': data.get('riskKey') or common.get('riskKey', ''),
        'es_pass': data.get('es_pass') or common.get('es_pass', ''),
        'seata_nacos_namespace': data.get('seata_nacos_namespace', ''),
        'middleware': data.get('middleware', [])
    }


def _get_common_settings():
    """从系统设置读取公共配置"""
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


def _get_setting_value(key, default=''):
    """从系统设置读取单个配置值"""
    s = Setting.query.filter_by(key=key).first()
    return s.value if s and s.value else default


def _get_candidate_nginx_conf_names(domain):
    """获取域名的候选 Nginx 配置文件名（兼容新旧两种命名）
    - 新格式: {domain}.conf          如 yshcsycd.hzbxhd.com.conf
    - 旧格式: {domain去点}.conf      如 yshcsycdhzbxhdcom.conf
    """
    names = [f'{domain}.conf']
    legacy = domain.replace('.', '') + '.conf'
    if legacy not in names:
        names.append(legacy)
    return names


def _recycle_nginx_config(domain, timestamp, log):
    """回收 Nginx 配置文件：移入回收站（远程 + 本地），兼容新旧命名

    Returns:
        dict: {file_name: {'remote': recycle_remote_path or None, 'local': recycle_local_path or None}}
              回收信息保存到 recycle_info 供恢复/彻底删除使用
    """
    from modules.nginx.service import NginxService
    nginx_remote_dir = _get_setting_value('nginx_remote_dir', '/etc/nginx/conf.d')
    nginx_local_dir = _get_setting_value('nginx_local_dir', './nginx_configs')
    recycle_remote_base = f'{nginx_remote_dir}/recycle'
    recycle_local_base = os.path.join(nginx_local_dir, 'recycle')

    candidates = _get_candidate_nginx_conf_names(domain)
    log('INFO', f'  域名: {domain}, 候选文件: {", ".join(candidates)}')

    recycle_info = {}
    nginx = None
    remote_changed = False

    for file_name in candidates:
        original_remote = f'{nginx_remote_dir}/{file_name}'
        original_local = os.path.join(nginx_local_dir, file_name)
        recycle_remote = f'{recycle_remote_base}/{file_name}.{timestamp}'
        recycle_local = os.path.join(recycle_local_base, f'{file_name}.{timestamp}')

        # 远程：移入回收站
        try:
            if nginx is None:
                nginx = NginxService()
            if nginx.host:
                nginx.exec_command(f'mkdir -p {recycle_remote_base}')
                if nginx.remote_file_exists(original_remote):
                    nginx.move_remote_file(original_remote, recycle_remote)
                    log('OK', f'  远程已移入回收站: {recycle_remote}')
                    remote_changed = True
                    recycle_info.setdefault(file_name, {})['remote'] = recycle_remote
        except Exception as e:
            log('WARN', f'  远程移动失败: {original_remote} - {str(e)}')

        # 本地：移入回收站
        if os.path.exists(original_local):
            try:
                os.makedirs(recycle_local_base, exist_ok=True)
                shutil.move(original_local, recycle_local)
                log('OK', f'  本地已移入回收站: {recycle_local}')
                recycle_info.setdefault(file_name, {})['local'] = recycle_local
            except Exception as e:
                log('WARN', f'  本地移动失败: {original_local} - {str(e)}')

    if remote_changed and nginx:
        ok, msg = nginx.reload_nginx()
        if ok:
            log('OK', '  Nginx已reload')
        else:
            log('WARN', f'  Nginx reload失败: {msg}')

    if not recycle_info:
        log('INFO', '  远程与本地配置均不存在，跳过')

    return recycle_info


def _restore_nginx_config(domain, recycle_info, log):
    """恢复 Nginx 配置文件：从回收站移回原处

    Args:
        domain: 域名
        recycle_info: _recycle_nginx_config 返回的回收信息 dict
    """
    if not recycle_info:
        log('INFO', '  无 Nginx 回收记录，跳过')
        return

    from modules.nginx.service import NginxService
    nginx_remote_dir = _get_setting_value('nginx_remote_dir', '/etc/nginx/conf.d')
    nginx_local_dir = _get_setting_value('nginx_local_dir', './nginx_configs')

    nginx = None
    remote_changed = False

    for file_name, paths in recycle_info.items():
        # 恢复远程
        remote_recycle = paths.get('remote')
        if remote_recycle:
            try:
                if nginx is None:
                    nginx = NginxService()
                if nginx.host:
                    original_remote = f'{nginx_remote_dir}/{file_name}'
                    if nginx.remote_file_exists(remote_recycle):
                        nginx.move_remote_file(remote_recycle, original_remote)
                        log('OK', f'  远程已恢复: {remote_recycle} -> {original_remote}')
                        remote_changed = True
            except Exception as e:
                log('WARN', f'  远程恢复失败: {remote_recycle} - {str(e)}')

        # 恢复本地
        local_recycle = paths.get('local')
        if local_recycle and os.path.exists(local_recycle):
            try:
                original_local = os.path.join(nginx_local_dir, file_name)
                os.makedirs(nginx_local_dir, exist_ok=True)
                shutil.move(local_recycle, original_local)
                log('OK', f'  本地已恢复: {local_recycle} -> {original_local}')
            except Exception as e:
                log('WARN', f'  本地恢复失败: {local_recycle} - {str(e)}')

    if remote_changed and nginx:
        ok, msg = nginx.reload_nginx()
        if ok:
            log('OK', '  Nginx已reload')
        else:
            log('WARN', f'  Nginx reload失败: {msg}')


def _delete_nginx_config_recycle(recycle_info, domain, log):
    """彻底删除：删除 Nginx 回收站中的文件（远程 + 本地），同时清理原位置残留

    Args:
        recycle_info: _recycle_nginx_config 返回的回收信息 dict
        domain: 域名（用于回退清理原位置）
    """
    from modules.nginx.service import NginxService
    nginx_remote_dir = _get_setting_value('nginx_remote_dir', '/etc/nginx/conf.d')
    nginx_local_dir = _get_setting_value('nginx_local_dir', './nginx_configs')

    deleted_count = 0
    nginx = None

    # 1. 从回收站删除
    if recycle_info:
        for file_name, paths in recycle_info.items():
            remote_recycle = paths.get('remote')
            if remote_recycle:
                try:
                    if nginx is None:
                        nginx = NginxService()
                    if nginx.host and nginx.remote_file_exists(remote_recycle):
                        nginx.delete_remote_file(remote_recycle)
                        log('OK', f'  回收站远程已删除: {remote_recycle}')
                        deleted_count += 1
                except Exception as e:
                    log('WARN', f'  回收站远程删除失败: {remote_recycle} - {str(e)}')

            local_recycle = paths.get('local')
            if local_recycle and os.path.exists(local_recycle):
                try:
                    os.remove(local_recycle)
                    log('OK', f'  回收站本地已删除: {local_recycle}')
                    deleted_count += 1
                except Exception as e:
                    log('WARN', f'  回收站本地删除失败: {local_recycle} - {str(e)}')

    # 2. 回退清理原位置（回收时可能因某些原因未能移入回收站）
    for file_name in _get_candidate_nginx_conf_names(domain):
        original_remote = f'{nginx_remote_dir}/{file_name}'
        original_local = os.path.join(nginx_local_dir, file_name)

        if nginx is None:
            nginx = NginxService()
        try:
            if nginx.host and nginx.remote_file_exists(original_remote):
                nginx.delete_remote_file(original_remote)
                log('OK', f'  原位置远程已删除: {original_remote}')
                deleted_count += 1
        except Exception as e:
            log('WARN', f'  原位置远程删除失败: {original_remote} - {str(e)}')

        if os.path.exists(original_local):
            try:
                os.remove(original_local)
                log('OK', f'  原位置本地已删除: {original_local}')
                deleted_count += 1
            except Exception as e:
                log('WARN', f'  原位置本地删除失败: {original_local} - {str(e)}')

    if deleted_count == 0:
        log('INFO', '  回收站与原位置均无残留，跳过')


def _generate_nginx_config(project_name, env_name, data, log):
    """生成 Nginx 配置文件并推送至 Nginx 服务器

    流程:
    1. 从模板渲染配置内容
    2. 保存到本地 nginx_configs/ 目录
    3. 检查远程是否已存在（存在则报错不覆盖）
    4. 推送至 Nginx 服务器
    """
    from modules.nginx.service import NginxService

    # 1. 计算变量
    default_domain = _get_setting_value('default_domain', 'hzbxhd.com')
    domain = data.get('domain', '') or f'{project_name}{env_name}.{default_domain}'
    k8s_cluster_ip = _get_setting_value('k8s_cluster_ip', '')
    port_start = data.get('debug_port', 30000)
    node_port_base = data.get('node_port', port_start + 30)

    # Gateway NodePort = node_port_base + gateway服务index(6) + 1
    services_list = data.get('services', [])
    gateway_index = -1
    for i, svc in enumerate(services_list):
        svc_name = svc.get('name', svc.get('app_name', '')) if isinstance(svc, dict) else str(svc)
        if svc_name == 'gateway':
            gateway_index = i
            break
    if gateway_index == -1:
        # 默认服务列表中 gateway 在第7个(index=6)
        gateway_index = 6
    gateway_nodeport = node_port_base + gateway_index + 1

    # SSL证书路径（固定跟主域名一致）
    ssl_cert = f'/etc/nginx/cert/{default_domain}.pem'
    ssl_key = f'/etc/nginx/cert/{default_domain}.key'

    # 目录路径
    web_root = f'/www/{project_name}/{env_name}/web'
    upload_alias = f'/www/{project_name}/{env_name}/upload/public'
    html_alias = f'/www/{project_name}/{env_name}/html'
    h5_alias = f'/www/{project_name}/{env_name}/h5'

    # 文件名
    file_name = domain + '.conf'

    log('INFO', f'  域名: {domain}')
    log('INFO', f'  文件名: {file_name}')
    log('INFO', f'  K8s集群IP: {k8s_cluster_ip}')
    log('INFO', f'  Gateway NodePort: {gateway_nodeport}')
    log('INFO', f'  Web目录: {web_root}')

    # 2. 读取模板并渲染
    template_path = os.path.join('modules', 'deploy', 'templates', 'nginx.conf.tpl')
    if not os.path.exists(template_path):
        raise Exception(f'Nginx模板不存在: {template_path}')

    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()

    # 移除模板头部注释行（只保留实际配置）
    lines = template.split('\n')
    config_lines = []
    skip_header = True
    for line in lines:
        if skip_header:
            if line.startswith('# ───'):
                skip_header = False
                config_lines.append(line)
            continue
        config_lines.append(line)
    config_content = '\n'.join(config_lines)

    # 变量替换
    variables = {
        '{{server_name}}': domain,
        '{{ssl_cert}}': ssl_cert,
        '{{ssl_key}}': ssl_key,
        '{{web_root}}': web_root,
        '{{upload_alias}}': upload_alias,
        '{{html_alias}}': html_alias,
        '{{h5_alias}}': h5_alias,
        '{{k8s_cluster_ip}}': k8s_cluster_ip,
        '{{gateway_nodeport}}': str(gateway_nodeport),
    }
    for placeholder, value in variables.items():
        config_content = config_content.replace(placeholder, value)

    # 3. 保存到本地
    local_dir = _get_setting_value('nginx_local_dir', './nginx_configs')
    os.makedirs(local_dir, exist_ok=True)
    local_path = os.path.join(local_dir, file_name)
    with open(local_path, 'w', encoding='utf-8') as f:
        f.write(config_content)
    log('INFO', f'  本地已保存: {local_path}')

    # 4. 推送至远程 Nginx 服务器
    nginx_server = _get_setting_value('nginx_server', '')
    if not nginx_server:
        log('WARN', '  Nginx服务器未配置，仅保存本地')
        return

    remote_dir = _get_setting_value('nginx_remote_dir', '/etc/nginx/conf.d')
    remote_path = f'{remote_dir}/{file_name}'

    nginx = NginxService()
    if not nginx.host:
        log('WARN', '  Nginx服务连接失败，仅保存本地')
        return

    # 检查远程是否已存在
    if nginx.remote_file_exists(remote_path):
        raise Exception(f'远程已存在配置文件: {file_name}，不会覆盖')

    nginx.push_config(config_content, remote_path)
    log('OK', f'  已推送至远程: {remote_path}')


def _build_deploy_config(data):
    """构建部署配置JSON（存入数据库）"""
    # 从系统设置读取公共配置（如果data中没有提供）
    common = _get_common_settings()

    config = {
        'tag': datetime.now().strftime('%Y%m%d%H%M'),
        'domain': data.get('domain', ''),
        'debug_port': data.get('debug_port', 30000),
        'node_port': data.get('node_port', 30030),
        'jmx_port': data.get('jmx_port', 30060),
        'middleware_port': data.get('middleware_port', 30090),
        'middleware': data.get('middleware', []),
        'services': data.get('services', []),
        'source_env': data.get('source_env', ''),
        'publicurl': data.get('publicurl') or common.get('publicurl', ''),
        'privateurl': data.get('privateurl') or common.get('privateurl', ''),
        'publicbucket': data.get('publicbucket') or common.get('publicbucket', ''),
        'privatebucket': data.get('privatebucket') or common.get('privatebucket', ''),
        'ossak': data.get('ossak') or common.get('ossak', ''),
        'osssk': data.get('osssk') or common.get('osssk', ''),
        'encrypted': data.get('encrypted') or common.get('encrypted', ''),
        'riskKey': data.get('riskKey') or common.get('riskKey', ''),
        'es_pass': data.get('es_pass') or common.get('es_pass', ''),
    }
    return config

