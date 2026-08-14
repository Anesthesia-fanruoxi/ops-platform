# -*- coding: utf-8 -*-
"""
审计日志采集框架

- record_audit：同步落库（异常隔离——审计失败绝不影响业务，只记日志）
- 参数脱敏：密码/密钥/token/私钥/kubeconfig 打码，长文本截断
- build_diff：字段级 diff（old/new），供关键更新接口显式调用
- register_hooks(app)：全局拦截器自动记录写操作（POST/PUT/DELETE）
  排除：静态资源、SSE 流、Agent 心跳、审计自身查询
"""
import json
import logging
import re
import time

logger = logging.getLogger(__name__)

# 敏感字段名：命中则值打码
SENSITIVE_KEYS = re.compile(
    r'(password|passwd|pwd|secret|token|private[_-]?key|kubeconfig|ssh_pass|harbor_pass|api[_-]?key|authorization|'
    r'(?:^|_)?(?:pass|sk|key|secret|token)$)',
    re.I,
)
# 排除路径前缀（不记录）
SKIP_PREFIXES = (
    '/static/', '/favicon',
    '/api/monitor/stream',
    '/api/cicd/agent/',       # Agent 心跳/日志上报（高频且非管理操作）
    '/api/audit',             # 审计自身查询
    '/api/auth/',             # 认证事件由 record_auth_event 显式记录（避免与拦截器重复）
)
SKIP_METHODS = ('GET', 'HEAD', 'OPTIONS')
MAX_PARAM_LEN = 2000
MAX_DIFF_LEN = 4000

# path 前缀 → 审计模块名
MODULE_MAP = [
    ('/api/auth/', 'auth'),
    ('/api/users/', 'user'),
    ('/api/roles/', 'role'),
    ('/api/settings/', 'setting'),
    ('/api/menus', 'menu'),
    ('/api/cicd/credentials', 'credential'),
    ('/api/cicd/templates', 'template'),
    ('/api/cicd/dockerfiles', 'dockerfile'),
    ('/api/cicd/agents', 'agent'),
    ('/api/cicd/builds', 'build'),
    ('/api/admin/projects', 'project'),
    ('/api/admin/environments', 'environment'),
    ('/api/deploy/service-info/nacos', 'nacos'),
    ('/api/deploy/datasources', 'datasource'),
    ('/api/deploy/service-info', 'service_info'),
]
ACTION_MAP = {'POST': 'create', 'PUT': 'update', 'DELETE': 'delete'}


# ─── 脱敏 ─────────────────────────────────────────────────

def _mask_value(key, value):
    if SENSITIVE_KEYS.search(str(key)) and value not in (None, ''):
        s = str(value)
        if len(s) <= 8:
            return '****'
        return s[:2] + '****' + s[-2:]
    return value


def _mask_params(data, depth=0):
    """递归脱敏（dict/list/嵌套，深度限制；敏感字段值打码）"""
    if depth > 4:
        return '[深度截断]'
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            k = str(k)
            if SENSITIVE_KEYS.search(k):
                out[k] = _mask_value(k, v)
            else:
                out[k] = _mask_params(v, depth + 1)
        return out
    if isinstance(data, (list, tuple)):
        return [_mask_params(v, depth + 1) for v in data]
    return data


def _truncate(s, limit):
    s = str(s)
    if len(s) <= limit:
        return s
    return s[:limit] + f'...[截断 {len(s) - limit} 字符]'


# ─── 模块/动作推导 ────────────────────────────────────────

ACTION_WORDS = ('create', 'update', 'delete', 'install', 'uninstall', 'reset',
                'recycle', 'restore', 'sync', 'publish', 'test', 'trigger', 'start', 'stop')


def _derive(path, method):
    for prefix, module in MODULE_MAP:
        if path.startswith(prefix):
            if module == 'auth':
                return 'auth', (path.rstrip('/').rsplit('/', 1)[-1] or 'login')
            seg = path.rstrip('/').rsplit('/', 1)[-1]
            if seg in ACTION_WORDS:
                return module, seg
            return module, ACTION_MAP.get(method, method.lower())
    return 'api', ACTION_MAP.get(method, method.lower())


def _current_user():
    try:
        from flask import g
        user = getattr(g, 'current_user', None)
        if user:
            return user.id, getattr(user, 'username', '') or getattr(user, 'name', '') or ''
    except Exception:
        pass
    return None, ''


def _request_ip():
    try:
        from flask import request
        return request.headers.get('X-Real-IP', '') or request.remote_addr or ''
    except Exception:
        return ''


# ─── 落库 ─────────────────────────────────────────────────

def record_audit(module='', action='', result='success', detail='', params=None,
                 diff=None, method='', path='', ip='', latency_ms=0,
                 user_id=None, username=''):
    """落审计日志（异常隔离：失败只记日志，不影响业务）"""
    try:
        from core.db import db
        from modules.system.models import AuditLog
        rec = AuditLog(
            user_id=user_id, username=username or '',
            module=module, action=action, result=result,
            detail=(detail or '')[:500],
            method=method, path=(path or '')[:255], ip=(ip or '')[:64],
            latency_ms=int(latency_ms or 0),
        )
        if params is not None:
            rec.params = _truncate(json.dumps(_mask_params(params), ensure_ascii=False, default=str), MAX_PARAM_LEN)
        if diff is not None:
            rec.diff = _truncate(json.dumps(diff, ensure_ascii=False, default=str), MAX_DIFF_LEN)
        db.session.add(rec)
        db.session.commit()
    except Exception:
        logger.exception('[audit] 落库失败（不影响业务）')


def record_auth_event(action, result='success', detail='', username='', params=None, method='POST'):
    """认证事件（登录/登出/改密/管理员登录）显式记录"""
    uid = None
    if not username:
        uid, username = _current_user()
    record_audit(module='auth', action=action, result=result, detail=detail,
                 params=params, method=method, path='/api/auth/' + action,
                 ip=_request_ip(), user_id=uid, username=username)


def record_audit_diff(module, action, obj_id, old_dict, new_dict, fields=None,
                      result='success', detail='', username=''):
    """字段级 diff 审计：对比 old/new 字典，仅记录变化的字段（敏感字段只记'已变更'）"""
    diff = build_diff(old_dict, new_dict, fields)
    if not diff:
        return
    uid = None
    if not username:
        uid, username = _current_user()
    record_audit(module=module, action=action, result=result,
                 detail=(detail or '') or f'{module}.{action} id={obj_id}',
                 params={'id': obj_id}, diff=diff, path='',
                 ip=_request_ip(), user_id=uid, username=username)


# ─── 字段级 diff ──────────────────────────────────────────

def build_diff(old_dict, new_dict, fields=None):
    """返回 {field: {'old': ..., 'new': ...}}，仅含变化字段；敏感字段新值打码"""
    old_dict = old_dict or {}
    new_dict = new_dict or {}
    keys = fields if fields is not None else (set(old_dict) | set(new_dict))
    diff = {}
    for k in keys:
        if k not in old_dict and k not in new_dict:
            continue
        old_v = old_dict.get(k)
        new_v = new_dict.get(k)
        if old_v != new_v:
            diff[k] = {
                'old': _mask_value(k, old_v),
                'new': _mask_value(k, new_v),
            }
    return diff


# ─── 全局拦截器 ───────────────────────────────────────────

def register_hooks(app):
    """注册全局审计拦截器：写操作（POST/PUT/DELETE）自动记录"""
    @app.before_request
    def _audit_start():
        from flask import request
        request._audit_start = time.monotonic()

    @app.after_request
    def _audit_record(resp):
        try:
            from flask import request
            if request.method in SKIP_METHODS:
                return resp
            path = request.path or ''
            if path.startswith(SKIP_PREFIXES):
                return resp
            start = getattr(request, '_audit_start', None)
            latency_ms = int((time.monotonic() - start) * 1000) if start else 0
            code = resp.status_code
            result = 'success' if code < 400 else ('denied' if code in (401, 403) else 'failed')
            params = None
            if request.is_json:
                params = request.get_json(silent=True)
            elif request.form:
                params = dict(request.form)
            uid, username = _current_user()
            if not uid:
                # 未认证请求不记录（防匿名刷库）；认证事件由 record_auth_event 显式记录
                return resp
            module, action = _derive(path, request.method)
            record_audit(module=module, action=action, result=result,
                         params=params, method=request.method, path=path,
                         ip=_request_ip(), latency_ms=latency_ms,
                         user_id=uid, username=username)
        except Exception:
            logger.exception('[audit] 拦截器异常（不影响响应）')
        return resp
