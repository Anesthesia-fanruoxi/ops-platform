# -*- coding: utf-8 -*-
"""
设置分组定义（对应系统设置三个标签页）

- deploy / nginx / middleware：三个标签页
- internal：内部设置（不在任何标签页展示，如 agent_comm_secret）
"""

SETTING_GROUPS = {
    'deploy': [
        'yaml_output_dir', 'yaml_recycle_dir',
        'nfs_server', 'nfs_cluster_server', 'nfs_ssh_port', 'nfs_ssh_user', 'nfs_ssh_pass',
        'nfs_logs_mount', 'nfs_data_mount', 'nfs_datastorg_mount',
        'harbor_url', 'harbor_user', 'harbor_pass',
        'harbor_cleanup_keep_versions', 'harbor_cleanup_cron',
        'k8s_master_ip', 'k8s_cluster_ip', 'k8s_ssh_user', 'k8s_ssh_pass',
        'k8s_yaml_remote_dir', 'k8s_yaml_remote_recycle_dir',
        'default_domain', 'default_nacos_namespace',
        'default_publicurl', 'default_privateurl', 'default_publicbucket', 'default_privatebucket',
        'default_ossak', 'default_osssk',
        'default_encrypted', 'default_riskKey', 'default_es_pass',
        'ignored_projects',
    ],
    'nginx': [
        'nginx_server', 'nginx_ssh_port', 'nginx_ssh_user', 'nginx_ssh_pass',
        'nginx_remote_dir', 'nginx_local_dir',
    ],
    'middleware': [
        'mysql_default_user', 'mysql_default_pass',
        'redis_user', 'redis_pass',
        'rabbitmq_user', 'rabbitmq_pass',
        'nacos_user', 'nacos_pass',
    ],
    'platform': [
        'token_expire_hours',
        'password_min_length',
        'password_require_upper',
        'password_require_digit',
        'agent_comm_secret',
        'authplatform_base_url',
        'authplatform_platform_id',
        'authplatform_secret',
    ],
}

INTERNAL_TYPE = 'internal'


def group_of(key):
    """返回设置项所属分组（deploy/nginx/middleware/internal）"""
    for group, keys in SETTING_GROUPS.items():
        if key in keys:
            return group
    return INTERNAL_TYPE
