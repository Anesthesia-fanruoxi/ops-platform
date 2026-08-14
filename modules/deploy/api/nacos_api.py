# -*- coding: utf-8 -*-
"""
Nacos管理接口处理函数
"""
import uuid
from flask import request
from modules.deploy.services.nacos_service import NacosService
from core.response import success_response, error_response
from core.security import require_permission


def _build_nacos_service():
    """构建 Nacos 数据库连接服务（连接信息从系统设置表读取，未配置则报错）"""
    from modules.system.settings_service import get_setting, get_setting_int
    return NacosService(
        db_host=get_setting('nacos_db_host', ''),
        db_port=get_setting_int('nacos_db_port', 0),
        db_user=get_setting('nacos_db_user', ''),
        db_pass=get_setting('nacos_db_pass', ''),
    )


@require_permission('page:create')
def list_namespaces():
    """列出所有namespace"""
    try:
        nacos = _build_nacos_service()
        namespaces = nacos.list_namespaces()
        return success_response(namespaces)
    except Exception as e:
        return error_response(str(e), 500)


@require_permission('page:create')
def get_namespace(namespace_id):
    """获取单个namespace"""
    try:
        nacos = _build_nacos_service()
        namespace = nacos.get_namespace(namespace_id)
        if not namespace:
            return error_response(f"Namespace {namespace_id} not found", 404)
        return success_response(namespace)
    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def create_namespace():
    """
    创建namespace

    请求体:
    {
        "namespace_id": "可选，不传则自动生成",
        "namespace_name": "my-namespace",
        "namespace_desc": "描述"
    }
    """
    try:
        data = request.json
        if not data.get('namespace_name'):
            return error_response('namespace_name is required', 400)

        nacos = _build_nacos_service()
        namespace_id = data.get('namespace_id') or str(uuid.uuid4())

        nacos.create_namespace(
            namespace_id=namespace_id,
            namespace_name=data['namespace_name'],
            namespace_desc=data.get('namespace_desc', '')
        )

        return success_response({
            'namespace_id': namespace_id,
            'namespace_name': data['namespace_name']
        }, 'Namespace created successfully')

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def copy_namespace():
    """
    复制namespace（包括配置数据）

    请求体:
    {
        "source_namespace_id": "源namespace ID",
        "new_namespace_id": "新namespace ID（可选）",
        "new_namespace_name": "新namespace名称"
    }
    """
    try:
        data = request.json

        if not data.get('source_namespace_id'):
            return error_response('source_namespace_id is required', 400)
        if not data.get('new_namespace_name'):
            return error_response('new_namespace_name is required', 400)

        nacos = _build_nacos_service()
        new_namespace_id = data.get('new_namespace_id') or str(uuid.uuid4())

        result = nacos.copy_namespace(
            source_namespace_id=data['source_namespace_id'],
            new_namespace_id=new_namespace_id,
            new_namespace_name=data['new_namespace_name']
        )

        return success_response(result, 'Namespace copied successfully')

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy_project')
def delete_namespace(namespace_id):
    """删除namespace"""
    try:
        nacos = _build_nacos_service()
        nacos.delete_namespace(namespace_id)
        return success_response(None, f"Namespace {namespace_id} deleted successfully")
    except Exception as e:
        return error_response(str(e), 500)
