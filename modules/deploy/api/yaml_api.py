# -*- coding: utf-8 -*-
"""
YAML生成接口处理函数
"""
from flask import request, current_app
from modules.deploy.services.yaml_generator import YAMLGenerator
from core.response import success_response, error_response
from core.security import require_permission


@require_permission('page:create')
def generate_yaml():
    """
    生成YAML配置文件

    请求体:
    {
        "project_name": "jieyihua",
        "env_name": "test",
        "tag": "202401011200",
        "nacos_namespace": "168e12d3-437e-429b-995d-2751ce3495e0",
        "domain": "testjieyihua.hzbxhd.com",
        "debug_port": 30200,
        "node_port": 30230,
        "jmx_port": 30260,
        "middleware_port": 30290,
        "services": [
            {"name": "app", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "gateway", "xms": 2, "xmx": 8, "replicas": 1}
        ]
    }
    """
    try:
        data = request.json

        # 必填参数校验
        if not data.get('project_name'):
            return error_response('project_name is required', 400)
        if not data.get('env_name'):
            return error_response('env_name is required', 400)

        # 构建项目配置
        project_config = {
            'project_name': data['project_name'],
            'env_name': data['env_name'],
            'tag': data.get('tag', 'latest'),
            'nacos_namespace': data.get('nacos_namespace', ''),
            'domain': data.get('domain', ''),
            'debug_port': data.get('debug_port', 30000),
            'node_port': data.get('node_port', 30030),
            'jmx_port': data.get('jmx_port', 30060),
            'middleware_port': data.get('middleware_port', 30090),
            'publicurl': data.get('publicurl', ''),
            'privateurl': data.get('privateurl', ''),
            'ossak': data.get('ossak', ''),
            'osssk': data.get('osssk', ''),
            'publicbucket': data.get('publicbucket', ''),
            'privatebucket': data.get('privatebucket', ''),
            'encrypted': data.get('encrypted', ''),
            'riskKey': data.get('riskKey', ''),
            'es_pass': data.get('es_pass', ''),
            'seata_nacos_namespace': data.get('seata_nacos_namespace', ''),
        }

        # 获取服务列表
        services = data.get('services')
        if services:
            # 给每个服务添加index
            for i, svc in enumerate(services):
                svc['index'] = i

        # 生成YAML
        generator = YAMLGenerator()
        yaml_content = generator.generate_all(project_config, services)

        # 添加项目信息到返回结果
        yaml_content['project_name'] = data['project_name']
        yaml_content['env_name'] = data['env_name']

        return success_response(yaml_content, 'YAML generated successfully')

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def generate_and_save_yaml():
    """
    生成并保存YAML配置文件到本地

    请求体: 同 /generate
    """
    try:
        data = request.json

        # 必填参数校验
        if not data.get('project_name'):
            return error_response('project_name is required', 400)
        if not data.get('env_name'):
            return error_response('env_name is required', 400)

        # 构建项目配置
        project_config = {
            'project_name': data['project_name'],
            'env_name': data['env_name'],
            'tag': data.get('tag', 'latest'),
            'nacos_namespace': data.get('nacos_namespace', ''),
            'domain': data.get('domain', ''),
            'debug_port': data.get('debug_port', 30000),
            'node_port': data.get('node_port', 30030),
            'jmx_port': data.get('jmx_port', 30060),
            'middleware_port': data.get('middleware_port', 30090),
            'publicurl': data.get('publicurl', ''),
            'privateurl': data.get('privateurl', ''),
            'ossak': data.get('ossak', ''),
            'osssk': data.get('osssk', ''),
            'publicbucket': data.get('publicbucket', ''),
            'privatebucket': data.get('privatebucket', ''),
            'encrypted': data.get('encrypted', ''),
            'riskKey': data.get('riskKey', ''),
            'es_pass': data.get('es_pass', ''),
            'seata_nacos_namespace': data.get('seata_nacos_namespace', ''),
        }

        # 获取服务列表
        services = data.get('services')

        # 生成YAML
        generator = YAMLGenerator()
        yaml_content = generator.generate_all(project_config, services)

        # 保存到本地
        output_dir = data.get('output_dir', './output')
        saved_path = generator.save_to_files(output_dir, yaml_content)

        return success_response({
            'path': saved_path,
            'files': {
                'deployments': len(yaml_content.get('deployments', [])),
                'services': len(yaml_content.get('services', [])),
                'middleware': len(yaml_content.get('middleware', []))
            }
        }, 'YAML generated and saved successfully')

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def generate_deployment():
    """单独生成Deployment YAML"""
    try:
        data = request.json

        if not data.get('project_name') or not data.get('env_name'):
            return error_response('project_name and env_name are required', 400)

        generator = YAMLGenerator()
        yaml_content = generator.generate_deployment(
            data['project_name'],
            data['env_name'],
            data.get('service', {}),
            data
        )

        return success_response({'yaml': yaml_content})

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def generate_service():
    """单独生成Service YAML"""
    try:
        data = request.json

        if not data.get('project_name') or not data.get('env_name'):
            return error_response('project_name and env_name are required', 400)

        generator = YAMLGenerator()
        yaml_content = generator.generate_service(
            data['project_name'],
            data['env_name'],
            data.get('service', {}),
            data
        )

        return success_response({'yaml': yaml_content})

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def generate_middleware():
    """单独生成中间件YAML"""
    try:
        data = request.json

        if not data.get('middleware_type'):
            return error_response('middleware_type is required', 400)
        if not data.get('project_name') or not data.get('env_name'):
            return error_response('project_name and env_name are required', 400)

        generator = YAMLGenerator()
        yaml_content = generator.generate_middleware(
            data['middleware_type'],
            data['project_name'],
            data['env_name'],
            data.get('middleware_port', 30090)
        )

        return success_response({'yaml': yaml_content})

    except Exception as e:
        return error_response(str(e), 500)
