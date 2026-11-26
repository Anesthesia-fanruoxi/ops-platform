# -*- coding: utf-8 -*-
"""
YAML生成服务
"""
import os
import shutil
from datetime import datetime


class YAMLGenerator:
    """YAML配置文件生成器"""

    # 一键部署时中间件的固定端口槽位，避免端口散落；mysql-init 不占端口
    MIDDLEWARE_PORT_OFFSETS = {
        'mysql': 0,
        'rabbitmq': 1,
        'redis': 2,
        'apollo': 3,
        'elasticsearch': 4,
        'eureka': 5,
        'seata': 6,
        'xxl-job': 7,
        'zookeeper': 8,
        'nacos': 9,
        'kafka': 10,
        'mysql-nfs': 11,
    }

    def __init__(self):
        self.template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')

    def _middleware_port(self, middleware, base_port, index=0):
        name = str(middleware).replace('.yaml', '').strip()
        offset = self.MIDDLEWARE_PORT_OFFSETS.get(name)
        if offset is None:
            return int(base_port) + 20 + int(index)
        return int(base_port) + int(offset)

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
            'mysql_pass': self._get_db_setting('mysql_default_pass') or 'SgQHvsy9M7LWKBCz',
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
            'mysql_user': self._get_db_setting('mysql_default_user', 'root'),
            # 未配置时沿用历史默认值，保证 MySQL Secret 与依赖它的 Apollo/Seata/XXL 一致
            'mysql_pass': self._get_db_setting('mysql_default_pass') or 'SgQHvsy9M7LWKBCz',
            'rabbitmq_user': self._get_db_setting('rabbitmq_user', 'admin'),
            'rabbitmq_pass': self._get_db_setting('rabbitmq_pass'),
            'es_pass': self._get_db_setting('es_pass') or self._get_db_setting('default_es_pass'),
            'apollo_env': env_name,
            'apollo_env_upper': env_name.upper().replace('-', '_'),
            'storage_class': 'statefu-nfs',
            'image_pull_secret': 'harbor',
            # Job 名不能重复 apply：每次生成带时间戳，重复执行由 SQL 自身幂等兜住
            'init_job_tag': datetime.now().strftime('%Y%m%d%H%M%S'),
        }

        return self._replace_vars(template, variables)

    @staticmethod
    def _effective_middleware(middleware_list):
        """Apollo/Seata/XXL 依赖 MySQL 库表；选中任一者时自动补 MySQL 与初始化 Job"""
        def mw_name(m):
            if isinstance(m, dict):
                return str(m.get('name') or m.get('type') or '').strip()
            return str(m or '').strip()
        names = [mw_name(m).replace('.yaml', '') for m in (middleware_list or []) if mw_name(m)]
        names = list(dict.fromkeys(names))
        if any(x in ('apollo', 'seata', 'xxl-job') for x in names):
            if 'mysql' not in names:
                names.insert(0, 'mysql')
            if 'mysql-init' not in names:
                names.insert(names.index('mysql') + 1, 'mysql-init')
        if 'seata' in names and 'eureka' not in names:
            names.append('eureka')
        return names

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
        middleware_list = self._effective_middleware(project_config.get('middleware', []))
        base_middleware_port = project_config.get('middleware_port', 30090)

        for index, middleware in enumerate(middleware_list):
            middleware_port = self._middleware_port(middleware, base_middleware_port, index)
            middleware_yaml = self.generate_middleware(
                middleware, project_name, env_name, middleware_port
            )
            result['middleware'].append({
                'name': middleware,
                'yaml': middleware_yaml
            })

        return result

    def _repo_service_vars(self, project_config, svc, index):
        """仓库风格模板变量：平台命名/namespace/Harbor 镜像 + 仓库 YAML 的资源/探针/env"""
        from modules.deploy.services import repo_k8s_map
        project = project_config['project_name']
        env = project_config['env_name']
        service = svc['service']
        tag = str(project_config.get('tag') or 'latest')
        hub = self._hub_server() or ''
        image = f'{hub}/{project}-{env}/{service}:{tag}' if hub else f'{project}-{env}/{service}:{tag}'
        env_cfg = (svc.get('env') or {}).get(env) or {
            'profile': env, 'label': env.upper()
        }
        probes = svc.get('probes') or {}
        style = probes.get('style') or 'legacy'

        def probe(key, path, period, fail):
            p = probes.get(key) or {}
            return (p.get('path') or path, str(p.get('period') or period), str(p.get('fail') or fail))

        startup_path, startup_period, startup_failure = probe('startup', '/actuator/health', 10, 30)
        readiness_path, readiness_period, readiness_failure = probe('readiness', '/actuator/health/readiness', 5, 3)
        liveness_path, liveness_period, liveness_failure = probe('liveness', '/actuator/health', 10, 3)
        resources = svc.get('resources') or {}
        limits = resources.get('limits') or {}
        requests = resources.get('requests') or {}
        java_opts = svc.get('java_opts') or {}
        conv = repo_k8s_map.conventions()
        return {
            'app_name': f'{project}-{service}',
            'namespace': f'{project}-{env}-service',
            # 应用内置的 META-INF/app.properties 指向旧 Apollo，部署时统一覆盖到本环境 ConfigService
            'apollo_meta': f'http://apollo-configservice.{project}-{env}-middleware.svc.cluster.local:8080',
            'image': image,
            'image_pull_secret': project_config.get('image_pull_secret') or svc.get('pull_secret') or conv.get('pull_secret', 'harbor'),
            'service_port': str(conv.get('service_port') or 8080),
            'service_expose_port': str(conv.get('service_expose_port') or 80),
            'tag': tag,
            'replicas': str(svc.get('replicas') or 1),
            'profile': env_cfg.get('profile') or env,
            'env_label': env_cfg.get('label') or env.upper(),
            'java_opts_configmap': java_opts.get('config_map') or 'java-option',
            'java_opts_key': java_opts.get('key') or 'jdk8-agent',
            'cpu_limit': str(limits.get('cpu') or '4'),
            'mem_limit': str(limits.get('memory') or '2Gi'),
            'cpu_request': str(requests.get('cpu') or '100m'),
            'mem_request': str(requests.get('memory') or '512Mi'),
            'startup_path': startup_path,
            'startup_period': startup_period,
            'startup_failure': startup_failure,
            'readiness_path': readiness_path,
            'readiness_period': readiness_period,
            'readiness_failure': readiness_failure,
            'liveness_path': liveness_path,
            'liveness_period': liveness_period,
            'liveness_failure': liveness_failure,
        }, style

    def _render_repo_service(self, project_config, svc, index):
        variables, style = self._repo_service_vars(project_config, svc, index)
        dep_tpl = 'repo_deployment_new.yaml' if style == 'new' else 'repo_deployment_legacy.yaml'
        deployment = self._replace_vars(self._read_template(dep_tpl), variables)
        service = self._replace_vars(self._read_template('repo_service.yaml'), variables)
        name = variables['app_name']
        return {'name': name, 'yaml': deployment}, {'name': name, 'yaml': service}

    def generate_all_repo(self, project_config, services=None):
        """仓库风格生成：Deployment/Service 用仓库模板，public-config/middleware 仍用平台模板"""
        from modules.deploy.services import repo_k8s_map
        project_name = project_config['project_name']
        env_name = project_config['env_name']

        chosen = []
        if services:
            names = []
            for s in services:
                names.append(str(s.get('name') if isinstance(s, dict) else s).strip())
            for name in names:
                if not name:
                    continue
                svc = repo_k8s_map.get_service(name)
                if svc:
                    chosen.append(svc)
        else:
            chosen = repo_k8s_map.all_services()

        result = {
            'project_name': project_name,
            'env_name': env_name,
            'deployments': [],
            'services': [],
            'public_config': None,
            'middleware': [],
        }
        for index, svc in enumerate(chosen):
            dep, svc_yaml = self._render_repo_service(project_config, svc, index)
            result['deployments'].append(dep)
            result['services'].append(svc_yaml)
        # 生成所选中间件 YAML（与现有模板同目录/同命名；仓库风格不自动 apply）
        base_middleware_port = project_config.get('middleware_port', 30090)
        for index, mw in enumerate(self._effective_middleware(project_config.get('middleware') or [])):
            if not mw:
                continue
            middleware_port = self._middleware_port(mw, base_middleware_port, index)
            mw_yaml = self.generate_middleware(mw, project_name, env_name, middleware_port)
            result['middleware'].append({'name': mw, 'yaml': mw_yaml})
        return result

    def generate_repo_single(self, project_config, service_name, index=0):
        """仓库风格单服务（新增服务用）"""
        from modules.deploy.services import repo_k8s_map
        svc = repo_k8s_map.get_service(service_name)
        if not svc:
            raise ValueError(f'服务「{service_name}」没有仓库 YAML 映射')
        return self._render_repo_service(project_config, svc, index)

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
