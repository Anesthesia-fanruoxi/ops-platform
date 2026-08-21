# -*- coding: utf-8 -*-
"""
部署环境域路由注册：deploy / yaml / harbor / nacos / nfs / manage / project / admin
"""
from flask import Blueprint

deploy_bp = Blueprint('deploy', __name__)
harbor_bp = Blueprint('harbor', __name__)
nacos_bp = Blueprint('nacos', __name__)
nfs_bp = Blueprint('nfs', __name__)
manage_bp = Blueprint('manage', __name__)
project_bp = Blueprint('project', __name__)
admin_bp = Blueprint('admin', __name__)

# ─── deploy 路由 ─────────────────────────────────────────────
from modules.deploy.api.deploy_api import (
    execute_deploy_project, execute_deploy_env, execute_deploy_service,
    deploy_stream, deploy_status,
    recycle_async, restore_async, permanent_delete_async,
    batch_permanent_delete_async, batch_recycle_async, batch_restore_async
)

deploy_bp.add_url_rule('/execute/project', 'execute_deploy_project', execute_deploy_project, methods=['POST'])
deploy_bp.add_url_rule('/execute/env', 'execute_deploy_env', execute_deploy_env, methods=['POST'])
deploy_bp.add_url_rule('/execute/service', 'execute_deploy_service', execute_deploy_service, methods=['POST'])
deploy_bp.add_url_rule('/stream', 'deploy_stream', deploy_stream, methods=['GET'])
deploy_bp.add_url_rule('/status', 'deploy_status', deploy_status, methods=['GET'])
deploy_bp.add_url_rule('/recycle', 'recycle_async', recycle_async, methods=['POST'])
deploy_bp.add_url_rule('/restore', 'restore_async', restore_async, methods=['POST'])
deploy_bp.add_url_rule('/permanent-delete', 'permanent_delete_async', permanent_delete_async, methods=['POST'])
deploy_bp.add_url_rule('/batch-permanent-delete', 'batch_permanent_delete_async', batch_permanent_delete_async, methods=['POST'])
deploy_bp.add_url_rule('/batch-recycle', 'batch_recycle_async', batch_recycle_async, methods=['POST'])
deploy_bp.add_url_rule('/batch-restore', 'batch_restore_async', batch_restore_async, methods=['POST'])

# ─── 环境收藏（按用户隔离：列表/新增/删除） ───────────────────
from modules.deploy.api.favorite_api import (
    list_favorites, add_favorite, delete_favorite
)

deploy_bp.add_url_rule('/service-info/favorites', 'list_favorites', list_favorites, methods=['GET'])
deploy_bp.add_url_rule('/service-info/favorites', 'add_favorite', add_favorite, methods=['POST'])
deploy_bp.add_url_rule('/service-info/favorites/<int:fid>', 'delete_favorite', delete_favorite, methods=['DELETE'])

# ─── harbor 路由 ─────────────────────────────────────────────
from modules.deploy.api.harbor_api import (
    create_project as harbor_create_project,
    list_projects as harbor_list_projects,
    get_project as harbor_get_project,
    delete_project as harbor_delete_project,
    list_repositories, list_artifacts, setup_cleanup
)

harbor_bp.add_url_rule('/create-project', 'create_project', harbor_create_project, methods=['POST'])
harbor_bp.add_url_rule('/list-projects', 'list_projects', harbor_list_projects, methods=['GET'])
harbor_bp.add_url_rule('/get-project/<project_name>', 'get_project', harbor_get_project, methods=['GET'])
harbor_bp.add_url_rule('/delete-project/<project_name>', 'delete_project', harbor_delete_project, methods=['DELETE'])
harbor_bp.add_url_rule('/list-repositories/<project_name>', 'list_repositories', list_repositories, methods=['GET'])
harbor_bp.add_url_rule('/list-artifacts/<project_name>/<path:repository_name>', 'list_artifacts', list_artifacts, methods=['GET'])
harbor_bp.add_url_rule('/setup-cleanup', 'setup_cleanup', setup_cleanup, methods=['POST'])

# ─── nacos 路由 ──────────────────────────────────────────────
from modules.deploy.api.nacos_api import (
    list_namespaces, get_namespace, create_namespace,
    copy_namespace, delete_namespace
)

nacos_bp.add_url_rule('/list-namespaces', 'list_namespaces', list_namespaces, methods=['GET'])
nacos_bp.add_url_rule('/get-namespace/<namespace_id>', 'get_namespace', get_namespace, methods=['GET'])
nacos_bp.add_url_rule('/create-namespace', 'create_namespace', create_namespace, methods=['POST'])
nacos_bp.add_url_rule('/copy-namespace', 'copy_namespace', copy_namespace, methods=['POST'])
nacos_bp.add_url_rule('/delete-namespace/<namespace_id>', 'delete_namespace', delete_namespace, methods=['DELETE'])

# ─── nfs 路由 ────────────────────────────────────────────────
from modules.deploy.api.nfs_api import create_dirs, check_dirs, create_single_dir, check_single_dir

nfs_bp.add_url_rule('/create-dirs', 'create_dirs', create_dirs, methods=['POST'])
nfs_bp.add_url_rule('/check-dirs', 'check_dirs', check_dirs, methods=['POST'])
nfs_bp.add_url_rule('/create-single-dir', 'create_single_dir', create_single_dir, methods=['POST'])
nfs_bp.add_url_rule('/check-single-dir', 'check_single_dir', check_single_dir, methods=['POST'])

# ─── manage 路由（环境查询 / 验证 / 同步）─────────────────────
from modules.deploy.api.envs_api import (
    list_environments, list_deleted_environments,
    validate_project, validate_environment, validate_service,
    get_source_env_info, get_available_port, get_environment_detail
)

manage_bp.add_url_rule('/environments/list', 'list_environments', list_environments, methods=['GET'])
manage_bp.add_url_rule('/environments/deleted', 'list_deleted_environments', list_deleted_environments, methods=['GET'])
manage_bp.add_url_rule('/validate/project', 'validate_project', validate_project, methods=['GET'])
manage_bp.add_url_rule('/validate/environment', 'validate_environment', validate_environment, methods=['GET'])
manage_bp.add_url_rule('/validate/service', 'validate_service', validate_service, methods=['GET'])
manage_bp.add_url_rule('/environments/source-info', 'get_source_env_info', get_source_env_info, methods=['GET'])
manage_bp.add_url_rule('/environments/available-port', 'get_available_port', get_available_port, methods=['GET'])
manage_bp.add_url_rule('/environments/detail', 'get_environment_detail', get_environment_detail, methods=['GET'])

from modules.deploy.api.sync_api import refresh_environments

manage_bp.add_url_rule('/environments/refresh', 'refresh_environments', refresh_environments, methods=['POST'])

# ─── project 路由 ─────────────────────────────────────────────
from modules.deploy.api.project_api import (
    list_projects as project_list_projects,
    update_project, refresh_projects
)

project_bp.add_url_rule('/list', 'list_projects', project_list_projects, methods=['GET'])
project_bp.add_url_rule('/update', 'update_project', update_project, methods=['POST'])
project_bp.add_url_rule('/refresh', 'refresh_projects', refresh_projects, methods=['POST'])

# ─── admin 路由 ───────────────────────────────────────────────
from modules.deploy.api.admin_api import (
    list_projects as admin_list_projects,
    create_project as admin_create_project,
    delete_project as admin_delete_project,
    list_environments as admin_list_environments,
    get_environment, update_environment, delete_environment
)

admin_bp.add_url_rule('/projects', 'list_projects', admin_list_projects, methods=['GET'])
admin_bp.add_url_rule('/projects', 'create_project', admin_create_project, methods=['POST'])
admin_bp.add_url_rule('/projects/<int:project_id>', 'delete_project', admin_delete_project, methods=['DELETE'])
admin_bp.add_url_rule('/projects/<int:project_id>/environments', 'list_environments', admin_list_environments, methods=['GET'])
admin_bp.add_url_rule('/environments/<int:env_id>', 'get_environment', get_environment, methods=['GET'])
admin_bp.add_url_rule('/environments/<int:env_id>', 'update_environment', update_environment, methods=['PUT'])
admin_bp.add_url_rule('/environments/<int:env_id>', 'delete_environment', delete_environment, methods=['DELETE'])


# ─── service-info 路由（服务信息：日志/Nacos配置/部署YAML/SSE实时/环境变量）────
from modules.deploy.api.service_info_api import (
    list_services, pod_log_stream, service_yaml,
    nacos_config_detail, nacos_config_publish
)
from modules.deploy.api.service_info_stream_api import service_info_stream, service_envs
from modules.deploy.api.service_info_logfile_api import logfile_list, logfile_content, logfile_download

deploy_bp.add_url_rule('/service-info/list', 'service_info_list', list_services, methods=['GET'])
deploy_bp.add_url_rule('/service-info/stream', 'service_info_stream', service_info_stream, methods=['GET'])
deploy_bp.add_url_rule('/service-info/envs', 'service_info_envs', service_envs, methods=['GET'])
deploy_bp.add_url_rule('/service-info/log/stream', 'service_info_log_stream', pod_log_stream, methods=['GET'])
deploy_bp.add_url_rule('/service-info/yaml', 'service_info_yaml', service_yaml, methods=['GET'])
deploy_bp.add_url_rule('/service-info/nacos/config', 'service_info_nacos_config', nacos_config_detail, methods=['GET'])
deploy_bp.add_url_rule('/service-info/nacos/config', 'service_info_nacos_publish', nacos_config_publish, methods=['POST'])
deploy_bp.add_url_rule('/service-info/logfiles', 'service_info_logfiles', logfile_list, methods=['GET'])
deploy_bp.add_url_rule('/service-info/logfile/content', 'service_info_logfile_content', logfile_content, methods=['GET'])
deploy_bp.add_url_rule('/service-info/logfile/download', 'service_info_logfile_download', logfile_download, methods=['GET'])


def register(app):
    """注册部署环境域蓝图"""
    app.register_blueprint(deploy_bp, url_prefix='/api/deploy')
    app.register_blueprint(harbor_bp, url_prefix='/api/harbor')
    app.register_blueprint(nacos_bp, url_prefix='/api/nacos')
    app.register_blueprint(nfs_bp, url_prefix='/api/nfs')
    app.register_blueprint(project_bp, url_prefix='/api/project')
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    app.register_blueprint(manage_bp, url_prefix='/api/manage')
