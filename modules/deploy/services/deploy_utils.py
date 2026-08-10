# -*- coding: utf-8 -*-
"""
部署模块共享工具 - 任务管理、日志工具
"""
import os
import threading
from datetime import datetime

# 任务管理：{task_key} -> {status, log_file, started_at, project_name, env_name}
_deploy_tasks = {}
_tasks_lock = threading.Lock()


def _get_log_path(project_name, env_name, action='environment'):
    """获取日志文件路径: logs/{project}/{project}-{env}-{action}.log"""
    log_dir = os.path.join('logs', project_name)
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, f"{project_name}-{env_name}-{action}.log")


def _write_log(log_file, level, message, step=None):
    """写入一行日志到文件"""
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    step_str = f"[{step}] " if step else ""
    line = f"[{ts}] [{level}] {step_str}{message}\n"
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(line)
        f.flush()


def _clear_log(log_file):
    """清空日志文件"""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, 'w', encoding='utf-8') as f:
        pass
