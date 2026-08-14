# -*- coding: utf-8 -*-
"""
CI/CD 域路由注册：templates / credentials / dockerfiles / agents / builds / agent-comm
"""
from flask import Blueprint

# 用户态蓝图（JWT 鉴权）
template_bp = Blueprint('cicd_templates', __name__)
credential_bp = Blueprint('cicd_credentials', __name__)
dockerfile_bp = Blueprint('cicd_dockerfiles', __name__)
agent_bp = Blueprint('cicd_agents', __name__)
build_bp = Blueprint('cicd_builds', __name__)
schedule_bp = Blueprint('cicd_schedule', __name__)

# Agent 通信蓝图（双向 AES-GCM 加密，白名单放行）
agent_comm_bp = Blueprint('cicd_agent_comm', __name__)

# ─── 流程模板 ─────────────────────────────────────────────────
from modules.cicd.api.template_api import (
    list_templates, create_template, update_template,
    delete_template, get_template
)

template_bp.add_url_rule('', 'list_templates', list_templates, methods=['GET'])
template_bp.add_url_rule('', 'create_template', create_template, methods=['POST'])
template_bp.add_url_rule('/<int:template_id>', 'get_template', get_template, methods=['GET'])
template_bp.add_url_rule('/<int:template_id>', 'update_template', update_template, methods=['PUT'])
template_bp.add_url_rule('/<int:template_id>', 'delete_template', delete_template, methods=['DELETE'])

# ─── 凭据 ─────────────────────────────────────────────────────
from modules.cicd.api.credential_api import (
    list_credentials, get_credential, create_credential, update_credential,
    delete_credential
)

credential_bp.add_url_rule('', 'list_credentials', list_credentials, methods=['GET'])
credential_bp.add_url_rule('', 'create_credential', create_credential, methods=['POST'])
credential_bp.add_url_rule('/<int:cred_id>', 'get_credential', get_credential, methods=['GET'])
credential_bp.add_url_rule('/<int:cred_id>', 'update_credential', update_credential, methods=['PUT'])
credential_bp.add_url_rule('/<int:cred_id>', 'delete_credential', delete_credential, methods=['DELETE'])

# ─── Dockerfile 模板 ──────────────────────────────────────────
from modules.cicd.api.dockerfile_api import (
    list_dockerfiles, get_dockerfile, create_dockerfile, update_dockerfile,
    delete_dockerfile, preview_dockerfile
)

dockerfile_bp.add_url_rule('', 'list_dockerfiles', list_dockerfiles, methods=['GET'])
dockerfile_bp.add_url_rule('', 'create_dockerfile', create_dockerfile, methods=['POST'])
dockerfile_bp.add_url_rule('/<int:tpl_id>', 'get_dockerfile', get_dockerfile, methods=['GET'])
dockerfile_bp.add_url_rule('/<int:tpl_id>', 'update_dockerfile', update_dockerfile, methods=['PUT'])
dockerfile_bp.add_url_rule('/<int:tpl_id>', 'delete_dockerfile', delete_dockerfile, methods=['DELETE'])
dockerfile_bp.add_url_rule('/<int:tpl_id>/preview', 'preview_dockerfile', preview_dockerfile, methods=['GET'])

# ─── Agent 管理 ───────────────────────────────────────────────
from modules.cicd.api.agent_api import (
    list_agents, get_agent_detail, install_agent, install_agent_remote,
    install_agent_stream, delete_agent,
    reinstall_agent, uninstall_agent_remote, reset_agent_remote,
    update_agent_remote, update_agent_config, toggle_agent_disable, proxy_agent_log,
    get_agent_metrics_history,
    get_docker_cache_size
)

agent_bp.add_url_rule('', 'list_agents', list_agents, methods=['GET'])
agent_bp.add_url_rule('/<int:agent_id>/detail', 'get_agent_detail', get_agent_detail, methods=['GET'])
agent_bp.add_url_rule('/<int:agent_id>/log', 'proxy_agent_log', proxy_agent_log, methods=['GET'])
agent_bp.add_url_rule('/<int:agent_id>/metrics', 'get_agent_metrics_history', get_agent_metrics_history, methods=['GET'])
agent_bp.add_url_rule('/install', 'install_agent', install_agent, methods=['POST'])
agent_bp.add_url_rule('/install-remote', 'install_agent_remote', install_agent_remote, methods=['POST'])
agent_bp.add_url_rule('/install-stream/<task_id>', 'install_agent_stream', install_agent_stream, methods=['GET'])
agent_bp.add_url_rule('/<int:agent_id>', 'delete_agent', delete_agent, methods=['DELETE'])
agent_bp.add_url_rule('/<int:agent_id>/install', 'reinstall_agent', reinstall_agent, methods=['POST'])
agent_bp.add_url_rule('/<int:agent_id>/uninstall', 'uninstall_agent_remote', uninstall_agent_remote, methods=['POST'])
agent_bp.add_url_rule('/<int:agent_id>/reset', 'reset_agent_remote', reset_agent_remote, methods=['POST'])
agent_bp.add_url_rule('/<int:agent_id>/update', 'update_agent_remote', update_agent_remote, methods=['POST'])
agent_bp.add_url_rule('/<int:agent_id>/config', 'update_agent_config', update_agent_config, methods=['PUT'])
agent_bp.add_url_rule('/<int:agent_id>/toggle-disable', 'toggle_agent_disable', toggle_agent_disable, methods=['POST'])
agent_bp.add_url_rule('/<int:agent_id>/docker-cache', 'get_docker_cache_size', get_docker_cache_size, methods=['GET'])

# ─── 构建 ─────────────────────────────────────────────────────
from modules.cicd.api.build_api import (
    list_builds, trigger_build, get_build,
    cancel_build, rerun_build, stream_build, stream_build_steps_sse,
    proxy_build_log, env_cicd_view, list_branches, list_services, env_builds_stream
)

build_bp.add_url_rule('', 'list_builds', list_builds, methods=['GET'])
build_bp.add_url_rule('/trigger', 'trigger_build', trigger_build, methods=['POST'])
build_bp.add_url_rule('/<int:build_id>', 'get_build', get_build, methods=['GET'])
build_bp.add_url_rule('/<int:build_id>/cancel', 'cancel_build', cancel_build, methods=['POST'])
build_bp.add_url_rule('/<int:build_id>/rerun', 'rerun_build', rerun_build, methods=['POST'])
build_bp.add_url_rule('/<int:build_id>/steps', 'stream_build', stream_build, methods=['GET'])
build_bp.add_url_rule('/<int:build_id>/steps/stream', 'stream_build_steps', stream_build_steps_sse, methods=['GET'])
build_bp.add_url_rule('/<int:build_id>/log', 'proxy_build_log', proxy_build_log, methods=['GET'])
build_bp.add_url_rule('/branches', 'list_branches', list_branches, methods=['GET'])
build_bp.add_url_rule('/services', 'list_services', list_services, methods=['GET'])
build_bp.add_url_rule('/env/<int:environment_id>', 'env_cicd_view', env_cicd_view, methods=['GET'])
build_bp.add_url_rule('/env/<int:environment_id>/stream', 'env_builds_stream', env_builds_stream, methods=['GET'])

# ─── Agent 通信（白名单放行，AES-GCM 加密认证）─────────────────
from modules.cicd.api.agent_comm_api import (
    agent_register, agent_heartbeat, agent_poll,
    agent_build_step, agent_build_result
)

agent_comm_bp.add_url_rule('/register', 'register', agent_register, methods=['POST'])
agent_comm_bp.add_url_rule('/heartbeat', 'heartbeat', agent_heartbeat, methods=['POST'])
agent_comm_bp.add_url_rule('/poll', 'poll', agent_poll, methods=['POST'])
agent_comm_bp.add_url_rule('/build/<int:build_id>/step', 'build_step', agent_build_step, methods=['POST'])
agent_comm_bp.add_url_rule('/build/<int:build_id>/result', 'build_result', agent_build_result, methods=['POST'])

# ─── 调度中心（JWT 鉴权，SSE 用 query token）───────────────────
from modules.cicd.api.schedule_api import (
    schedule_overview, schedule_stream, schedule_logs, schedule_log_detail, schedule_scores,
)

schedule_bp.add_url_rule('/overview', 'overview', schedule_overview, methods=['GET'])
schedule_bp.add_url_rule('/stream', 'stream', schedule_stream, methods=['GET'])
schedule_bp.add_url_rule('/logs', 'logs', schedule_logs, methods=['GET'])
schedule_bp.add_url_rule('/logs/<int:log_id>', 'log_detail', schedule_log_detail, methods=['GET'])
schedule_bp.add_url_rule('/scores', 'scores', schedule_scores, methods=['GET'])


def register(app):
    """注册 CI/CD 域蓝图"""
    app.register_blueprint(template_bp, url_prefix='/api/cicd/templates')
    app.register_blueprint(credential_bp, url_prefix='/api/cicd/credentials')
    app.register_blueprint(dockerfile_bp, url_prefix='/api/cicd/dockerfiles')
    app.register_blueprint(agent_bp, url_prefix='/api/cicd/agents')
    app.register_blueprint(build_bp, url_prefix='/api/cicd/builds')
    app.register_blueprint(agent_comm_bp, url_prefix='/api/cicd/agent')
    app.register_blueprint(schedule_bp, url_prefix='/api/cicd/schedule')
