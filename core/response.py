# -*- coding: utf-8 -*-
"""
统一响应格式
"""
from flask import jsonify


def success_response(data=None, msg='success'):
    """成功响应"""
    response = jsonify({
        'code': 200,
        'msg': msg,
        'data': data
    })
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response


def error_response(msg='error', code=500, data=None):
    """错误响应（HTTP状态码与业务code一致）"""
    response = jsonify({
        'code': code,
        'msg': msg,
        'data': data
    })
    response.status_code = code
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response
