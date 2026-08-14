# -*- coding: utf-8 -*-
"""
Nacos Open API HTTP 客户端（服务信息页配置查看/修改用）

- 地址解析：环境 middleware 目录中 nacos 的 NodePort + 系统设置 k8s_master_ip
- tenant：Environment.nacos_namespace
- 鉴权自动兼容：先匿名调用，401/403 时用系统设置 nacos_user/nacos_pass 登录重试；
  accessToken 按地址内存缓存（提前 60s 过期刷新）
"""
import os
import time
import threading

import yaml

from modules.system.settings_service import get_setting

_TOKEN_CACHE = {}   # base_url -> (access_token, expire_ts)
_TOKEN_LOCK = threading.Lock()
_HTTP_TIMEOUT = 10


def resolve_nacos_endpoint(project, env):
    """解析环境 Nacos 的访问地址与 tenant

    Returns:
        (base_url, tenant)，base_url 形如 http://{master_ip}:{nodePort}/nacos

    Raises:
        ValueError: 环境未配置 nacos_namespace / 未找到 nacos NodePort / master IP 未配置
    """
    from modules.deploy.models import Environment, Project

    proj = Project.query.filter_by(name=project).first()
    if not proj:
        raise ValueError(f'项目 {project} 不存在')
    env_rec = Environment.query.filter_by(project_id=proj.id, name=env, is_deleted=False).first()
    if not env_rec:
        raise ValueError(f'环境 {project}-{env} 不存在')
    tenant = env_rec.nacos_namespace or ''
    if not tenant:
        raise ValueError(f'环境 {project}-{env} 未配置 nacos_namespace，请先在环境同步/编辑中补充')

    node_port = _find_nacos_node_port(project, env)
    if not node_port:
        raise ValueError(f'未找到环境 {project}-{env} 的 Nacos NodePort（middleware 目录无 nacos NodePort Service）')

    master_ip = get_setting('k8s_master_ip', '')
    if not master_ip:
        raise ValueError('系统设置未配置 k8s_master_ip，无法定位 Nacos 地址')

    return f'http://{master_ip}:{node_port}/nacos', tenant


def _find_nacos_node_port(project, env):
    """从本地生成目录 {output_dir}/{project-env}/middleware 解析 nacos NodePort"""
    from modules.deploy.api.shared import get_output_dir

    mw_dir = os.path.join(get_output_dir(), f'{project}-{env}', 'middleware')
    if not os.path.exists(mw_dir):
        return ''
    for f in sorted(os.listdir(mw_dir)):
        if not (f.endswith('.yaml') or f.endswith('.yml')):
            continue
        if 'nacos' not in f.lower():
            continue
        try:
            with open(os.path.join(mw_dir, f), 'r', encoding='utf-8') as fp:
                docs = list(yaml.safe_load_all(fp.read()))
            for doc in docs:
                if doc and doc.get('kind') == 'Service':
                    spec = doc.get('spec', {})
                    if spec.get('type') == 'NodePort':
                        ports = spec.get('ports', [])
                        if ports:
                            return str(ports[0].get('nodePort', ''))
        except Exception:
            continue
    return ''


class NacosHttpClient:
    """Nacos Open API 客户端（单环境单地址）"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.username = get_setting('nacos_user', '')
        self.password = get_setting('nacos_pass', '')

    # ─── 鉴权 ─────────────────────────────────────────────

    def _cached_token(self):
        with _TOKEN_LOCK:
            item = _TOKEN_CACHE.get(self.base_url)
            if item and item[1] > time.time():
                return item[0]
        return None

    def _login(self):
        """账号登录获取 accessToken；未配置账号时抛错"""
        import requests
        if not self.username or not self.password:
            raise ValueError('Nacos 需要鉴权，但系统设置未配置 nacos_user/nacos_pass')
        resp = requests.post(
            f'{self.base_url}/v1/auth/login',
            data={'username': self.username, 'password': self.password},
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code != 200:
            raise ValueError(f'Nacos 登录失败（{resp.status_code}）: {resp.text[:200]}')
        data = resp.json()
        token = data.get('accessToken', '')
        ttl = int(data.get('tokenTtl', 18000))
        with _TOKEN_LOCK:
            _TOKEN_CACHE[self.base_url] = (token, time.time() + max(ttl - 60, 60))
        return token

    def _request(self, method, path, params=None, data=None):
        """带鉴权自动兼容的请求：先匿名，401/403 时登录重试一次"""
        import requests
        url = f'{self.base_url}{path}'

        def _do(token):
            p = dict(params or {})
            if token:
                p['accessToken'] = token
            return requests.request(
                method, url, params=p if method == 'GET' else None,
                data=data, timeout=_HTTP_TIMEOUT,
            )

        token = self._cached_token()
        resp = _do(token)
        if resp.status_code in (401, 403):
            resp = _do(self._login())
        return resp

    # ─── 配置接口 ─────────────────────────────────────────

    def list_configs(self, tenant, keyword='', page_no=1, page_size=50):
        """列出 namespace 下配置（dataId 模糊搜索）"""
        resp = self._request('GET', '/v1/cs/configs', params={
            'search': 'blur' if keyword else 'accurate',
            'dataId': keyword or '',
            'group': '',
            'tenant': tenant,
            'pageNo': page_no,
            'pageSize': page_size,
        })
        if resp.status_code != 200:
            raise ValueError(f'查询配置列表失败（{resp.status_code}）: {resp.text[:200]}')
        data = resp.json()
        items = [{
            'dataId': it.get('dataId', ''),
            'group': it.get('group', ''),
            'type': it.get('type', ''),
            'appName': it.get('appName', ''),
        } for it in data.get('pageItems', [])]
        return {'total': data.get('totalCount', 0), 'items': items}

    def get_config(self, tenant, data_id, group):
        """获取单个配置内容"""
        resp = self._request('GET', '/v1/cs/configs', params={
            'dataId': data_id, 'group': group, 'tenant': tenant,
        })
        if resp.status_code != 200:
            raise ValueError(f'获取配置失败（{resp.status_code}）: {resp.text[:200]}')
        return resp.text

    def publish_config(self, tenant, data_id, group, content):
        """发布/更新配置，返回是否成功"""
        resp = self._request('POST', '/v1/cs/configs', data={
            'dataId': data_id, 'group': group, 'tenant': tenant, 'content': content,
        })
        if resp.status_code != 200:
            raise ValueError(f'发布配置失败（{resp.status_code}）: {resp.text[:200]}')
        body = (resp.text or '').strip()
        if body.lower() != 'true':
            raise ValueError(f'发布配置失败: {body[:200]}')
        return True
