# -*- coding: utf-8 -*-
"""
部署服务
整合所有部署步骤
"""
from flask import current_app
from modules.deploy.services.yaml_generator import YAMLGenerator
from modules.deploy.services.nfs_service import NFSService
from modules.deploy.services.nacos_service import NacosService
from modules.deploy.services.harbor_client import HarborClient
from modules.deploy.projects_config import get_project_config, get_project_env_config


class DeployService:
    """部署服务"""

    def __init__(self):
        pass

    def _get_harbor_client(self):
        """获取Harbor客户端（优先从数据库读取配置）"""
        from modules.system.models import Setting

        def _get_setting(key, default):
            try:
                s = Setting.query.filter_by(key=key).first()
                return s.value if s and s.value else default
            except Exception:
                return default

        return HarborClient(
            harbor_url=_get_setting('harbor_url', ''),
            username=_get_setting('harbor_user', ''),
            password=_get_setting('harbor_pass', ''),
        )

    def deploy(self, project_name, env_name, source_env=None, mode='copy'):
        """
        一键部署

        Args:
            project_name: 项目名称
            env_name: 目标环境名称
            source_env: 源环境名称（copy模式必填）
            mode: 部署模式 (copy-复制, create-新建)

        Returns:
            dict: 部署结果
        """
        result = {
            'project_name': project_name,
            'env_name': env_name,
            'mode': mode,
            'steps': []
        }

        # 获取项目配置
        project_config = get_project_config(project_name)
        if not project_config:
            raise ValueError(f"Project '{project_name}' not found")

        env_config = project_config.get('envs', {}).get(env_name)
        if not env_config:
            raise ValueError(f"Environment '{env_name}' not found for project '{project_name}'")

        services = project_config.get('services', [])
        middleware = project_config.get('middleware', [])

        # Step 1: 生成YAML文件
        try:
            step_result = self._step_generate_yaml(
                project_name, env_name, env_config, services, middleware
            )
            result['steps'].append({
                'name': 'generate_yaml',
                'status': 'success',
                'data': step_result
            })
        except Exception as e:
            result['steps'].append({
                'name': 'generate_yaml',
                'status': 'failed',
                'error': str(e)
            })
            return result

        # Step 2: 创建目录
        try:
            step_result = self._step_create_dirs(project_name, env_name, services)
            result['steps'].append({
                'name': 'create_dirs',
                'status': 'success',
                'data': step_result
            })
        except Exception as e:
            result['steps'].append({
                'name': 'create_dirs',
                'status': 'failed',
                'error': str(e)
            })

        # Step 3: 复制数据（copy模式）
        if mode == 'copy' and source_env:
            try:
                step_result = self._step_copy_data(
                    project_name, source_env, env_name, services
                )
                result['steps'].append({
                    'name': 'copy_data',
                    'status': 'success',
                    'data': step_result
                })
            except Exception as e:
                result['steps'].append({
                    'name': 'copy_data',
                    'status': 'failed',
                    'error': str(e)
                })

        # Step 4: 创建Harbor项目
        try:
            step_result = self._step_create_harbor_project(project_name, env_name)
            result['steps'].append({
                'name': 'create_harbor_project',
                'status': 'success',
                'data': step_result
            })
        except Exception as e:
            result['steps'].append({
                'name': 'create_harbor_project',
                'status': 'failed',
                'error': str(e)
            })

        return result

    def _step_generate_yaml(self, project_name, env_name, env_config, services, middleware):
        """Step 1: 生成YAML文件"""
        # 构建项目配置
        full_config = {
            'project_name': project_name,
            'env_name': env_name,
            'tag': env_config.get('tag', 'latest'),
            'nacos_namespace': env_config.get('nacos_namespace', ''),
            'domain': env_config.get('domain', ''),
            'debug_port': env_config.get('debug_port', 30000),
            'node_port': env_config.get('node_port', 30030),
            'jmx_port': env_config.get('jmx_port', 30060),
            'middleware_port': env_config.get('middleware_port', 30090),
            'publicurl': env_config.get('publicurl', ''),
            'privateurl': env_config.get('privateurl', ''),
            'ossak': env_config.get('ossak', ''),
            'osssk': env_config.get('osssk', ''),
            'publicbucket': env_config.get('publicbucket', ''),
            'privatebucket': env_config.get('privatebucket', ''),
            'encrypted': env_config.get('encrypted', ''),
            'riskKey': env_config.get('riskKey', ''),
            'es_pass': env_config.get('es_pass', ''),
            'seata_nacos_namespace': env_config.get('seata_nacos_namespace', ''),
        }

        # 生成YAML
        generator = YAMLGenerator()
        yaml_content = generator.generate_all(full_config, services)

        # 保存到本地
        output_dir = current_app.config.get('OUTPUT_DIR', './output')
        saved_path = generator.save_to_files(output_dir, yaml_content)

        return {
            'path': saved_path,
            'files': {
                'deployments': len(yaml_content.get('deployments', [])),
                'services': len(yaml_content.get('services', [])),
                'middleware': len(yaml_content.get('middleware', []))
            }
        }

    def _step_create_dirs(self, project_name, env_name, services):
        """Step 2: 创建目录"""
        nfs = NFSService()
        result = nfs.create_project_dirs(project_name, env_name, services)
        return result

    def _step_copy_data(self, project_name, source_env, dest_env, services):
        """Step 3: 复制数据"""
        nfs = NFSService()
        result = nfs.copy_project_dirs(project_name, source_env, project_name, dest_env, services)
        return result

    def _step_create_harbor_project(self, project_name, env_name):
        """Step 4: 创建Harbor项目"""
        harbor = self._get_harbor_client()
        project_name_full = f"{project_name}-{env_name}"

        # 检查项目是否已存在
        existing_project = harbor.get_project(project_name_full)
        if existing_project:
            return {
                'project_name': project_name_full,
                'status': 'already_exists'
            }

        # 创建项目（公有）
        result = harbor.create_project(
            project_name=project_name_full,
            public=True,
            metadata={'auto_scan': 'true'}
        )

        if result['success']:
            # 设置清理策略
            keep_raw = _get_setting('harbor_cleanup_keep_versions', '')
            keep_versions = int(keep_raw) if keep_raw else 3
            cron = _get_setting('harbor_cleanup_cron', '') or '0 0 * * * *'

            import time
            time.sleep(2)

            # 获取项目ID，用于关联保留策略
            proj_info = harbor.get_project(project_name_full)
            project_id = proj_info.get('project_id') if proj_info else None
            retention_ref = project_id if project_id else project_name_full

            harbor.create_retention_policy(
                project_name_or_id=retention_ref,
                keep_recent=keep_versions,
                cron=cron
            )

        return {
            'project_name': project_name_full,
            'status': 'created' if result['success'] else 'failed',
            'cleanup': {
                'keep_versions': keep_versions,
                'cron': cron
            }
        }
