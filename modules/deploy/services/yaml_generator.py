# -*- coding: utf-8 -*-
"""
YAML生成服务
"""
import os
import shutil


class YAMLGenerator:
    """YAML配置文件生成器"""

    def __init__(self):
        self.template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

    @staticmethod
    def _get_db_setting(key, default=''):
        """从系统设置表读取配置；不存在返回空（不生成默认值）"""
        try:
            from modules.system.settings_service import get_setting
            return get_setting(key, default)
        except Exception:
            return default

    @staticmethod
    def _hub_server():
        """镜像仓库域名：取 harbor_url 去掉协议前缀（harbor 地址即仓库域名）"""
        url = YAMLGenerator._get_db_setting('harbor_url')
        if not url:
            return ''
        return url.replace('https://', '').replace('http://', '').rstrip('/')

    def _read_template(self, template_name):
        """读取模板文件"""
        template_path = os.path.join(self.template_dir, template_name)
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()

    def _replace_vars(self, content, variables):
        """替换模板变量"""
        for key, value in variables.items():
            content = content.replace(f'${{{key}}}', str(value))
        return content

    def generate_deployment(self, project_name, env_name, service_config, project_config):
        """
        生成Deployment YAML

        Args:
            project_name: 项目名称
            env_name: 环境名称
            service_config: 服务配置 {"name": "app", "xms": 2, "xmx": 8, "replicas": 1}
            project_config: 项目配置 {"tag": "xxx", "nacos_namespace": "xxx", "domain": "xxx", ...}
        """
        template = self._read_template('deployment_mod.yaml')

        # 构建变量
        app_name = f"{project_name}-{service_config['name']}"
        variables = {
            'app_name': app_name,
            'name': service_config['name'],
            'project_name': project_name,
            'env_name': env_name,
            'tag': project_config.get('tag', 'latest'),
            'nacos_namespace': project_config.get('nacos_namespace', ''),
            'domain': project_config.get('domain', ''),
            'xms': str(service_config.get('xms', 2)),
            'xmx': str(service_config.get('xmx', 8)),
            'replicas': str(service_config.get('replicas', 1)),
            'debug_port': str(project_config.get('debug_port', 5000)),
            'debug_port_internal': '5000',
            'service_port': '8080',
            'jmx_port': str(project_config.get('jmx_port', 8081)),
            'jmx_port_internal': '8081',
            'logs_mount': self._get_db_setting('nfs_logs_mount'),
            'data_mount': self._get_db_setting('nfs_data_mount'),
            'nfs_server': self._get_db_setting('nfs_cluster_server'),
            'hub_server': self._hub_server(),
            'redis_pass': self._get_db_setting('redis_pass'),
            'mq_pass': self._get_db_setting('rabbitmq_pass'),
            'mysql_pass': self._get_db_setting('mysql_default_pass'),
            'publicurl': project_config.get('publicurl', ''),
            'privateurl': project_config.get('privateurl', ''),
            'ossak': project_config.get('ossak', ''),
            'osssk': project_config.get('osssk', ''),
            'publicbucket': project_config.get('publicbucket', ''),
            'privatebucket': project_config.get('privatebucket', ''),
            'encrypted': project_config.get('encrypted', ''),
            'riskKey': project_config.get('riskKey', ''),
            'es_pass': project_config.get('es_pass', ''),
            'seata_nacos_namespace': project_config.get('seata_nacos_namespace', ''),
        }

        return self._replace_vars(template, variables)

    def generate_service(self, project_name, env_name, service_config, project_config):
        """
        生成Service YAML

        Args:
            project_name: 项目名称
            env_name: 环境名称
            service_config: 服务配置
            project_config: 项目配置
        """
        template = self._read_template('service_mod.yaml')

        # 端口计算（基于基础端口 + 偏移）
        base_debug_port = project_config.get('debug_port', 30000)
        base_node_port = project_config.get('node_port', 30030)
        base_jmx_port = project_config.get('jmx_port', 30060)

        # 计算当前服务的端口偏移
        service_index = service_config.get('index', 0)
        debug_port = base_debug_port + service_index + 1
        node_port = base_node_port + service_index + 1
        jmx_port = base_jmx_port + service_index + 1

        # 内部端口（固定值）
        debug_port_internal = 5000
        service_port = 8080
        jmx_port_internal = 8081

        app_name = f"{project_name}-{service_config['name']}"
        variables = {
            'app_name': app_name,
            'project_name': project_name,
            'env_name': env_name,
            'debug_port': str(debug_port),
            'node_port': str(node_port),
            'jmx_port': str(jmx_port),
            'debug_port_internal': str(debug_port_internal),
            'service_port': str(service_port),
            'jmx_port_internal': str(jmx_port_internal),
        }

        return self._replace_vars(template, variables)

    def generate_public_config(self, project_name, env_name, service_config=None):
        """生成公共配置YAML"""
        template = self._read_template('public-config.yaml')

        # 如果有service_config，使用它来获取变量值
        app_name = f"{project_name}-{service_config['name']}" if service_config else f"{project_name}-app"

        variables = {
            'project_name': project_name,
            'env_name': env_name,
            'project': project_name,
            'environment': env_name,
            'pod_name': app_name,
        }

        return self._replace_vars(template, variables)

    def generate_middleware(self, middleware_type, project_name, env_name, middleware_port):
        """
        生成中间件YAML

        Args:
            middleware_type: 中间件类型 (nacos/mysql/redis/kafka/rabbitmq/mysql-nfs)
            project_name: 项目名称
            env_name: 环境名称
            middleware_port: 中间件端口
        """
        template_name = f'{middleware_type}.yaml'
        template = self._read_template(template_name)

        variables = {
            'project_name': project_name,
            'env_name': env_name,
            'middleware_port': str(middleware_port),
            'hub_server': self._hub_server(),
            'nfs_server': self._get_db_setting('nfs_cluster_server'),
            'data_mount': self._get_db_setting('nfs_data_mount'),
            'redis_pass': self._get_db_setting('redis_pass'),
            'mq_pass': self._get_db_setting('rabbitmq_pass'),
        }

        return self._replace_vars(template, variables)

    def generate_all(self, project_config, services=None):
        """
        生成所有YAML文件

        Args:
            project_config: 项目配置
            services: 服务列表，如果为None则使用默认配置

        Returns:
            dict: 生成的YAML文件内容
        """
        project_name = project_config['project_name']
        env_name = project_config['env_name']

        # 未配置服务列表则不生成默认服务（先配置好，再生成配置）
        services = services or []

        result = {
            'project_name': project_name,
            'env_name': env_name,
            'deployments': [],
            'services': [],
            'public_config': None,
            'middleware': []
        }

        # 生成Deployment和Service
        for index, service in enumerate(services):
            service['index'] = index

            # Deployment
            deployment_yaml = self.generate_deployment(
                project_name, env_name, service, project_config
            )
            result['deployments'].append({
                'name': f"{project_name}-{service['name']}",
                'yaml': deployment_yaml
            })

            # Service
            service_yaml = self.generate_service(
                project_name, env_name, service, project_config
            )
            result['services'].append({
                'name': f"{project_name}-{service['name']}",
                'yaml': service_yaml
            })

        # 生成公共配置
        result['public_config'] = {
            'name': 'public-config',
            'yaml': self.generate_public_config(project_name, env_name, services[0] if services else None)
        }

        # 生成中间件 - 使用用户传递的middleware参数
        middleware_list = project_config.get('middleware', [])
        base_middleware_port = project_config.get('middleware_port', 30090)

        for index, middleware in enumerate(middleware_list):
            middleware_port = base_middleware_port + index
            middleware_yaml = self.generate_middleware(
                middleware, project_name, env_name, middleware_port
            )
            result['middleware'].append({
                'name': middleware,
                'yaml': middleware_yaml
            })

        return result

    def save_to_files(self, output_dir, yaml_content):
        """
        将YAML内容保存到文件

        Args:
            output_dir: 输出目录
            yaml_content: generate_all返回的内容
        """
        project_name = yaml_content.get('project_name', 'unknown')
        env_name = yaml_content.get('env_name', 'unknown')
        base_dir = os.path.join(output_dir, f"{project_name}-{env_name}")

        # 创建目录结构
        dirs = ['deployment', 'service', 'middleware']
        for d in dirs:
            os.makedirs(os.path.join(base_dir, d), exist_ok=True)

        # 保存Deployment
        for item in yaml_content.get('deployments', []):
            file_path = os.path.join(base_dir, 'deployment', f"{item['name']}.yaml")
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(item['yaml'])

        # 保存Service
        for item in yaml_content.get('services', []):
            file_path = os.path.join(base_dir, 'service', f"{item['name']}.yaml")
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(item['yaml'])

        # 保存公共配置
        public_config = yaml_content.get('public_config')
        if public_config:
            file_path = os.path.join(base_dir, 'public-config.yaml')
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(public_config['yaml'])

        # 保存中间件
        for item in yaml_content.get('middleware', []):
            file_path = os.path.join(base_dir, 'middleware', f"{item['name']}.yaml")
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(item['yaml'])

        return base_dir
