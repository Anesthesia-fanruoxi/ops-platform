# -*- coding: utf-8 -*-
"""
构建后自动部署：构建成功（镜像已推送 Harbor）后，由 Master 经 SSH 修改远程部署 YAML 的
镜像 tag 并 kubectl apply（远程为主，随后同步本地副本）。全程在 Master 侧完成，Agent 无需安装 k8s 工具。

- 全部构建：修改所有已构建服务的 tag，kubectl apply 整个 deployment 目录
- 部分构建：仅修改指定服务的 tag，kubectl apply 对应单个 YAML 文件
- best-effort：部署失败仅记录日志，不影响构建终态（构建已 success）
"""
import os
import re
import logging
import threading
from datetime import datetime

from flask import current_app

logger = logging.getLogger(__name__)

# 部署日志目录（与构建日志同目录，{build_no}.deploy.log）
DEPLOY_LOG_DIR = os.path.join('logs', 'cicd')

# 同环境串行化锁：避免并发构建同时对同一环境的 YAML 做 sed+apply 产生竞态
_env_locks_guard = threading.Lock()
_env_locks = {}


def _env_lock(env_full):
    """获取/创建指定环境的串行化锁"""
    with _env_locks_guard:
        lock = _env_locks.get(env_full)
        if lock is None:
            lock = threading.Lock()
            _env_locks[env_full] = lock
        return lock


def _acquire_env_lock(env_full, local_lock, log):
    """获取同环境部署锁：Redis 分布式锁优先，Redis 不可用降级进程内锁；最长等待 5 分钟。
    返回 (mode, token)；超时返回 (None, None)（无锁继续，best-effort）"""
    import time
    from core.redis_client import acquire_lock_mixed
    for _ in range(300):
        mode, token = acquire_lock_mixed(f'lock:deploy:{env_full}', local_lock, ttl=600000)
        if mode is not None:
            return mode, token
        time.sleep(1)
    log('WARN', '等待同环境部署锁超时（5分钟），继续执行（存在并发竞态风险）')
    return None, None


def trigger_auto_deploy(build_id):
    """构建成功后触发自动部署（后台线程，不阻塞 Agent 加密响应）"""
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        logger.warning(f'[AutoDeploy] 无应用上下文，跳过构建#{build_id} 自动部署')
        return
    t = threading.Thread(target=_run, args=(app, build_id), daemon=True)
    t.start()


def _run(app, build_id):
    """后台线程：在独立应用上下文中加载构建并执行部署"""
    with app.app_context():
        from modules.cicd.models import Build
        build = Build.query.get(build_id)
        if not build:
            logger.warning(f'[AutoDeploy] 构建#{build_id} 不存在，跳过自动部署')
            return
        try:
            auto_deploy_build(build)
        except Exception as e:
            logger.exception(f'[AutoDeploy] 构建#{build_id} 自动部署异常: {e}')
            # 兜底结束部署步骤：异常路径未走 finish()，避免部署步骤永久 running（时间一直累加）
            try:
                from modules.cicd.services.build_service import update_deploy_step
                update_deploy_step(build.build_no, 'failed', f'自动部署异常: {e}')
            except Exception:
                pass


def auto_deploy_build(build):
    """对成功的构建执行自动部署：改远程 YAML 镜像 tag + kubectl apply"""
    project_name = build.project.name if build.project else ''
    env_name = build.environment.name if build.environment else ''
    if not project_name or not env_name:
        logger.warning(f'[AutoDeploy] 构建#{build.id} 缺少项目/环境信息，跳过自动部署')
        return

    env_full = f'{project_name}-{env_name}'
    new_tag = build.image_tag or ''
    snapshot = build.get_steps_snapshot()

    # 实际构建并推送的服务名 = artifact_dirs 的 basename；selected 为空或覆盖全部服务 = 全部构建
    all_names = [d.strip().rstrip('/').split('/')[-1] for d in snapshot.get('artifact_dirs', []) if d.strip()]
    selected = snapshot.get('services') or []
    # 全选（selected 覆盖全部服务）与未选（空）都按「全部构建」处理；只有真正的部分选择才逐文件 apply
    is_full = (not selected) or set(selected) >= set(all_names)
    target = selected if selected else all_names

    log_path = _deploy_log_path(build.build_no)
    has_error = [False]

    def log(level, msg):
        # 增量写入部署日志，供前端 SSE 实时 tail
        line = f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} [{level}] {msg}'
        _append_log(log_path, line)
        getattr(logger, 'info' if level in ('INFO', 'OK') else 'warning')(f'[AutoDeploy#{build.id}] {msg}')
        if level == 'ERROR':
            has_error[0] = True

    # 进入部署：标记 build.json 中「部署」步骤为 running（供步骤 SSE 推送）
    from modules.cicd.services.build_service import update_deploy_step
    update_deploy_step(build.build_no, 'running')

    def finish():
        """根据是否有 ERROR 结束部署步骤（不影响构建终态）"""
        if has_error[0]:
            update_deploy_step(build.build_no, 'failed', '部署过程中存在错误，详见部署日志')
        else:
            update_deploy_step(build.build_no, 'success')

    log('INFO', f'开始自动部署：环境={env_full} tag={new_tag} 范围={"全部" if is_full else "部分"} 服务={target}')

    if build.project_type == 'backend' and not all_names:
        # 后端未配置服务目录：编译完成但未收集产物/打镜像，部署步骤等待平台勾选回填后重新构建
        log('WARN', '未配置服务目录，无法部署：请在部署步骤点「配置服务目录」勾选后重新构建')
        update_deploy_step(build.build_no, 'waiting', '未配置服务目录，请配置后重新构建')
        return

    if not new_tag:
        log('WARN', '构建无镜像 tag，跳过自动部署')
        update_deploy_step(build.build_no, 'success')
        return
    if not target:
        log('WARN', '无可部署的服务，跳过自动部署')
        update_deploy_step(build.build_no, 'success')
        return

    # 懒导入 deploy 模块，避免 cicd↔deploy 循环依赖
    from modules.deploy.services.k8s_service import K8sService
    from modules.deploy.api.shared import get_k8s_yaml_remote_dir

    k8s = K8sService()
    if not k8s.host:
        log('WARN', '未配置 K8s 控制节点（k8s_master_ip），跳过自动部署')
        update_deploy_step(build.build_no, 'success')
        return

    deploy_dir = f'{get_k8s_yaml_remote_dir()}/{env_full}/deployment'

    # 同环境串行化：sed+apply 非原子，避免并发构建竞态。
    # 跨 worker 用 Redis 分布式锁，Redis 不可用降级进程内锁；获取失败等待重试。
    env_lock = _env_lock(env_full)
    lock_mode, lock_token = _acquire_env_lock(env_full, env_lock, log)
    try:
        # SSH 全程复用一次连接（connect 建在获锁后，避免等锁期间空闲断连）
        k8s.connect()
        if not k8s.remote_directory_exists(deploy_dir):
            log('WARN', f'远程部署目录不存在（环境未部署）：{deploy_dir}，跳过自动部署')
            update_deploy_step(build.build_no, 'success')
            return

        # 1. 修改镜像 tag：远程为主（远程文件可能是最新变更，不能用本地覆盖），
        #    复用同一 SSH 连接逐文件 sed，随后同步本地副本保持一致；
        #    不批量 sed 整个目录 —— 各服务 tag 可能不一致，未构建服务的 tag 必须保持不动
        applied_files = []
        for svc in target:
            yaml_path = f'{deploy_dir}/{svc}.yaml'
            r = k8s.exec_command(f'test -f {yaml_path} && echo EXISTS')
            if r['stdout'] != 'EXISTS':
                log('WARN', f'部署文件不存在，跳过: {svc}.yaml')
                continue
            sed = f'sed -i "s#{env_full}/{svc}:[^[:space:]]*#{env_full}/{svc}:{new_tag}#g" {yaml_path}'
            r = k8s.exec_command(sed)
            if r['exit_code'] != 0:
                log('ERROR', f'修改 tag 失败: {svc}.yaml - {r["stderr"]}')
                continue
            log('OK', f'已修改 tag: {svc}.yaml -> {env_full}/{svc}:{new_tag}')
            _sync_local_yaml_tag(env_full, svc, new_tag, log)
            applied_files.append(svc)

        if not applied_files:
            log('WARN', '无可应用的部署文件，结束自动部署')
            finish()
            return

        # 2. apply：全部构建 apply 整个目录（所有服务 tag 均为本次新 tag，一条命令高效应用）；
        #    部分构建只 apply 涉及的文件（未构建服务不触碰）
        if is_full:
            r = k8s.exec_command(f'kubectl apply -f {deploy_dir}/', timeout=120)
            if r['exit_code'] == 0:
                log('OK', f'已应用部署目录: {deploy_dir}/')
            else:
                log('ERROR', f'应用部署目录失败: {deploy_dir} - {r["stderr"]}')
        else:
            for svc in applied_files:
                r = k8s.exec_command(f'kubectl apply -f {deploy_dir}/{svc}.yaml', timeout=120)
                if r['exit_code'] == 0:
                    log('OK', f'已应用: {svc}.yaml')
                else:
                    log('ERROR', f'应用失败: {svc}.yaml - {r["stderr"]}')
    finally:
        k8s.close()
        if lock_mode is not None:
            from core.redis_client import release_lock_mixed
            release_lock_mixed(f'lock:deploy:{env_full}', lock_mode, lock_token, env_lock)

    log('INFO', '自动部署流程结束')
    finish()


def _sync_local_yaml_tag(env_full, svc, new_tag, log):
    """同步修改本地 YAML 文件的镜像 tag（{output_dir}/{env_full}/deployment/{svc}.yaml），
    保持本地与服务端一致，便于读取本地 YAML 了解项目信息（无需每次 SSH）。
    best-effort：失败仅 WARN，不影响远程部署流程。"""
    from modules.deploy.api.shared import get_output_dir
    local_path = os.path.join(get_output_dir(), env_full, 'deployment', f'{svc}.yaml')
    if not os.path.isfile(local_path):
        log('WARN', f'本地部署文件不存在，跳过同步: {local_path}')
        return
    try:
        with open(local_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        pattern = re.escape(f'{env_full}/{svc}') + r':[^\s]*'
        new_content, n = re.subn(pattern, f'{env_full}/{svc}:{new_tag}', content)
        if n == 0:
            log('WARN', f'本地 {svc}.yaml 未找到镜像 tag 行，跳过同步: {local_path}')
            return
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        log('INFO', f'已同步本地 tag: {svc}.yaml -> {env_full}/{svc}:{new_tag}')
    except OSError as e:
        log('WARN', f'同步本地 {svc}.yaml 失败: {e}')


def _deploy_log_path(build_no):
    """部署日志文件路径：logs/cicd/{build_no}.deploy.log"""
    os.makedirs(DEPLOY_LOG_DIR, exist_ok=True)
    return os.path.join(DEPLOY_LOG_DIR, f'{build_no}.deploy.log')


def _append_log(log_path, line):
    """增量追加单行部署日志（供 SSE 实时读取）"""
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError as e:
        logger.warning(f'[AutoDeploy] 写入部署日志失败: {e}')
