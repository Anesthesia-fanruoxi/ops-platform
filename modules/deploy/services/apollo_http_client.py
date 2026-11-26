# -*- coding: utf-8 -*-
"""
Apollo Portal 客户端（服务信息页 Apollo 配置查看/修改用）

- 地址解析：环境 middleware 目录中 apollo-portal 的 NodePort + 系统设置 k8s_master_ip
- 鉴权：系统设置 apollo_user/apollo_pass 登录 Portal（POST /signin，复用 JSESSIONID 会话）
- 接口：Apollo Portal 2.5.x 内部 REST API（与 Portal 前端同源）；不直接改 Apollo 数据库
- 发布：item 增删改后创建 release，客户端才能感知变更
"""
import os
import threading

import yaml

from modules.system.settings_service import get_setting

_HTTP_TIMEOUT = 15
_SESSION_LOCK = threading.Lock()


def resolve_apollo_endpoint(project, env):
    """解析环境 Apollo Portal 访问地址，返回 http://{master_ip}:{nodePort}"""
    node_port = _find_apollo_portal_node_port(project, env)
    if not node_port:
        raise ValueError(f'环境 {project}-{env} 未部署 Apollo Portal（middleware 目录无 apollo-portal NodePort）')
    master_ip = get_setting('k8s_master_ip', '')
    if not master_ip:
        raise ValueError('系统设置未配置 k8s_master_ip，无法定位 Apollo Portal 地址')
    return f'http://{master_ip}:{node_port}'


def env_has_apollo(project, env):
    """环境是否部署了 Apollo：middleware 生成目录存在 apollo-portal NodePort 即视为已部署"""
    try:
        return bool(_find_apollo_portal_node_port(project, env))
    except Exception:
        return False


def _find_apollo_portal_node_port(project, env):
    from modules.deploy.api.shared import get_output_dir

    mw_dir = os.path.join(get_output_dir(), f'{project}-{env}', 'middleware')
    if not os.path.isdir(mw_dir):
        return ''
    for f in sorted(os.listdir(mw_dir)):
        if not f.lower().startswith('apollo') or not f.endswith(('.yaml', '.yml')):
            continue
        try:
            with open(os.path.join(mw_dir, f), 'r', encoding='utf-8') as fp:
                docs = list(yaml.safe_load_all(fp.read()))
        except Exception:
            continue
        for doc in docs:
            if not doc or doc.get('kind') != 'Service':
                continue
            meta = doc.get('metadata') or {}
            if meta.get('name') != 'apollo-portal':
                continue
            spec = doc.get('spec') or {}
            if spec.get('type') != 'NodePort':
                continue
            for p in spec.get('ports') or []:
                if p.get('nodePort'):
                    return str(p['nodePort'])
    return ''


class ApolloHttpClient:
    """Apollo Portal 客户端（单环境单地址）"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.username = get_setting('apollo_user', '') or 'apollo'
        self.password = get_setting('apollo_pass', '') or 'admin'
        self.session = None
        self._env_name = ''
        self._env_cache = None

    # ─── 会话 ─────────────────────────────────────────────

    def _ensure_session(self):
        if self.session is not None:
            return
        import requests
        s = requests.Session()
        s.trust_env = False
        try:
            s.post(
                f'{self.base_url}/signin',
                data={'username': self.username, 'password': self.password},
                allow_redirects=False,
                timeout=_HTTP_TIMEOUT,
            )
            check = s.get(f'{self.base_url}/apps', allow_redirects=False, timeout=_HTTP_TIMEOUT)
        except Exception as e:
            raise ValueError(f'连接 Apollo Portal 失败：{e}')
        if check.status_code in (301, 302):
            raise ValueError('Apollo Portal 登录失败，请检查系统设置中的 apollo_user/apollo_pass')
        with _SESSION_LOCK:
            self.session = s

    def reset_session(self):
        self.session = None

    def _request(self, method, path, **kwargs):
        self._ensure_session()
        kwargs.setdefault('timeout', _HTTP_TIMEOUT)
        resp = self.session.request(method, f'{self.base_url}{path}', allow_redirects=False, **kwargs)
        if resp.status_code in (301, 302) and '/signin' in (resp.headers.get('Location') or ''):
            self.reset_session()
            self._ensure_session()
            resp = self.session.request(method, f'{self.base_url}{path}', allow_redirects=False, **kwargs)
        return resp

    @staticmethod
    def _error(resp, action):
        msg = ''
        try:
            body = resp.json()
            msg = body.get('message') or body.get('error') or ''
        except Exception:
            msg = (resp.text or '')[:200]
        if resp.status_code == 403:
            return f'{action}失败：当前 Apollo 账号无权限（{msg or "403"}）'
        return f'{action}失败（{resp.status_code}）：{msg or "未知错误"}'

    # ─── 环境 / 应用 / namespace ──────────────────────────

    def resolve_env(self, env_name):
        """把平台环境名映射为 Portal 环境名（TEST/DEV/...）"""
        if self._env_name:
            return self._env_name
        resp = self._request('GET', '/envs')
        if resp.status_code != 200:
            raise ValueError(self._error(resp, '读取 Apollo 环境列表'))
        envs = resp.json() or []
        if not envs:
            raise ValueError('Apollo Portal 未配置任何环境')
        want = (env_name or '').upper().replace('-', '_')
        for e in envs:
            if e == want or e.upper() == want:
                self._env_name = e
                return e
        for e in envs:
            if e.lower() == (env_name or '').lower():
                self._env_name = e
                return e
        self._env_name = envs[0]
        return self._env_name

    def find_app(self, app_id):
        resp = self._request('GET', '/apps', params={'appIds': app_id})
        if resp.status_code != 200:
            raise ValueError(self._error(resp, '查询 Apollo 应用'))
        for app in resp.json() or []:
            if app.get('appId') == app_id and not app.get('isDeleted'):
                return app
        return None

    def resolve_app_id(self, project, service):
        """服务名 → Apollo appId。

        K8s 服务卡片名可能带项目/环境前缀（goshop-bill-config），而 Apollo appId 通常是
        仓库服务名（bill-config）：先按原样匹配，再尝试去掉 {project}- 前缀；
        仍未命中时按「appId 为服务名后缀」匹配（取最长，避免 bill-config/config 歧义）。
        """
        candidates = [service]
        prefix = f'{project}-'
        if service.startswith(prefix) and len(service) > len(prefix):
            candidates.append(service[len(prefix):])
        for app_id in candidates:
            if self.find_app(app_id):
                return app_id
        resp = self._request('GET', '/apps')
        if resp.status_code != 200:
            return ''
        matches = [
            a.get('appId', '') for a in resp.json() or []
            if a.get('appId') and not a.get('isDeleted')
            and (a['appId'] == service or service.endswith('-' + a['appId']))
        ]
        return max(matches, key=len) if matches else ''

    def list_namespaces(self, app_id, env):
        """返回 [{name, namespaceId}]，按 Portal 返回顺序"""
        resp = self._request('GET', f'/apps/{app_id}/envs/{env}/clusters/default/namespaces')
        if resp.status_code != 200:
            # 应用存在但没有任何 namespace 时 Portal 返回 400 namespace not exist
            if resp.status_code == 400:
                return []
            raise ValueError(self._error(resp, '读取 Apollo namespace'))
        result = []
        for bo in resp.json() or []:
            base = bo.get('baseInfo') or {}
            if base.get('namespaceName'):
                result.append({
                    'name': base['namespaceName'],
                    'namespaceId': base.get('id', 0),
                    'isPublic': bool(bo.get('isPublic')),
                })
        return result

    # ─── 配置项 ───────────────────────────────────────────

    def get_items(self, app_id, env, namespace):
        resp = self._request(
            'GET', f'/apps/{app_id}/envs/{env}/clusters/default/namespaces/{namespace}/items')
        if resp.status_code != 200:
            raise ValueError(self._error(resp, '读取 Apollo 配置'))
        items = []
        for it in resp.json() or []:
            items.append({
                'id': it.get('id'),
                'namespaceId': it.get('namespaceId'),
                'key': it.get('key', ''),
                'value': it.get('value', ''),
                'comment': it.get('comment', '') or '',
                'lineNum': it.get('lineNum', 0),
            })
        return items

    def create_item(self, app_id, env, namespace, key, value, comment=''):
        resp = self._request(
            'POST', f'/apps/{app_id}/envs/{env}/clusters/default/namespaces/{namespace}/item',
            json={'key': key, 'value': value, 'comment': comment})
        if resp.status_code not in (200, 201):
            raise ValueError(self._error(resp, f'新增配置项 {key}'))

    def update_item(self, app_id, env, namespace, item, value):
        payload = {
            'id': item.get('id'),
            'namespaceId': item.get('namespaceId'),
            'key': item.get('key'),
            'value': value,
            'comment': item.get('comment', '') or '',
        }
        resp = self._request(
            'PUT', f'/apps/{app_id}/envs/{env}/clusters/default/namespaces/{namespace}/item',
            json=payload)
        if resp.status_code != 200:
            raise ValueError(self._error(resp, f'更新配置项 {item.get("key")}'))

    def delete_item(self, app_id, env, namespace, item):
        resp = self._request(
            'DELETE',
            f'/apps/{app_id}/envs/{env}/clusters/default/namespaces/{namespace}/items/{item.get("id")}')
        if resp.status_code != 200:
            raise ValueError(self._error(resp, f'删除配置项 {item.get("key")}'))

    def publish(self, app_id, env, namespace, title, comment=''):
        resp = self._request(
            'POST', f'/apps/{app_id}/envs/{env}/clusters/default/namespaces/{namespace}/releases',
            json={
                'releaseTitle': title,
                'releasedBy': self.username,
                'releaseComment': comment,
                'isEmergencyPublish': False,
            })
        if resp.status_code != 200:
            raise ValueError(self._error(resp, '发布 Apollo 配置'))
        return resp.json() or {}


# ─── 配置文本编解码（key=value，properties 风格）─────────────

def _escape_value(value):
    v = (value or '').replace('\\', '\\\\').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    lead = len(v) - len(v.lstrip(' '))
    if lead:
        v = '\\ ' * lead + v[lead:]
    return v


def _escape_key(key):
    k = (key or '').replace('\\', '\\\\').replace('=', '\\=').replace(':', '\\:').replace(' ', '\\ ')
    if k[:1] in ('#', '!'):
        k = '\\' + k
    return k


def _unescape(text):
    out = []
    i = 0
    mapping = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', ' ': ' ', '=': '=', ':': ':', '#': '#', '!': '!'}
    while i < len(text):
        ch = text[i]
        if ch == '\\' and i + 1 < len(text):
            nxt = text[i + 1]
            out.append(mapping.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return ''.join(out)


def _split_property(line):
    escaped = False
    for i, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == '\\':
            escaped = True
            continue
        if ch in '=:':
            return line[:i], line[i + 1:]
    return line, ''


def items_to_text(items):
    """Apollo items → 可编辑文本（按 lineNum/id 排序）"""
    out = []
    for it in sorted(items, key=lambda x: (x.get('lineNum') or 0, x.get('id') or 0)):
        out.append(f"{_escape_key(it.get('key', ''))}={_escape_value(it.get('value', ''))}")
    return '\n'.join(out)


def text_to_items(text):
    """可编辑文本 → [{key, value, line}]；返回 (items, errors)"""
    items = []
    errors = []
    seen = {}
    for lineno, raw in enumerate((text or '').splitlines(), 1):
        line = raw.rstrip('\r')
        stripped = line.lstrip(' \t')
        if not stripped or stripped[0] in ('#', '!'):
            continue
        key_raw, value_raw = _split_property(stripped)
        key = _unescape(key_raw.strip())
        if not key:
            errors.append(f'第 {lineno} 行 key 为空')
            continue
        if key in seen:
            errors.append(f'第 {lineno} 行 key 重复（首次出现在第 {seen[key]} 行）：{key}')
            continue
        seen[key] = lineno
        items.append({'key': key, 'value': _unescape(value_raw.lstrip(' \t')), 'line': lineno})
    return items, errors