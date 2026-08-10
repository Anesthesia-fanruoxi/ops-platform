# -*- coding: utf-8 -*-
"""
NFS远程目录管理接口处理函数
"""
from flask import request
from modules.deploy.services.nfs_service import NFSService
from core.response import success_response, error_response
from core.security import require_permission


@require_permission('op:deploy')
def create_dirs():
    """
    为项目创建所有NFS目录

    请求体:
    {
        "project_name": "jieyihua",
        "env_name": "test",
        "services": [
            {"name": "app"},
            {"name": "gateway"},
            ...
        ]
    }
    """
    try:
        data = request.json

        if not data.get('project_name'):
            return error_response('project_name is required', 400)
        if not data.get('env_name'):
            return error_response('env_name is required', 400)

        services = data.get('services', [])
        if not services:
            return error_response('services list is required', 400)

        nfs = NFSService()
        result = nfs.create_project_dirs(
            data['project_name'],
            data['env_name'],
            services
        )

        return success_response(result, 'Directories created successfully')

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('page:create')
def check_dirs():
    """
    检查项目目录是否存在

    请求体:
    {
        "project_name": "jieyihua",
        "env_name": "test",
        "services": [
            {"name": "app"},
            {"name": "gateway"},
            ...
        ]
    }
    """
    try:
        data = request.json

        if not data.get('project_name'):
            return error_response('project_name is required', 400)
        if not data.get('env_name'):
            return error_response('env_name is required', 400)

        services = data.get('services', [])
        if not services:
            return error_response('services list is required', 400)

        nfs = NFSService()
        results = nfs.check_project_dirs(
            data['project_name'],
            data['env_name'],
            services
        )

        return success_response(results)

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('op:deploy')
def create_single_dir():
    """
    创建单个目录

    请求体:
    {
        "path": "/data/logs/test/test-app"
    }
    """
    try:
        data = request.json
        if not data.get('path'):
            return error_response('path is required', 400)

        nfs = NFSService()
        nfs.create_directory(data['path'])

        return success_response({'path': data['path']}, 'Directory created successfully')

    except Exception as e:
        return error_response(str(e), 500)


@require_permission('page:create')
def check_single_dir():
    """
    检查单个目录是否存在

    请求体:
    {
        "path": "/data/logs/test/test-app"
    }
    """
    try:
        data = request.json
        if not data.get('path'):
            return error_response('path is required', 400)

        nfs = NFSService()
        exists = nfs.directory_exists(data['path'])

        return success_response({
            'path': data['path'],
            'exists': exists
        })

    except Exception as e:
        return error_response(str(e), 500)
