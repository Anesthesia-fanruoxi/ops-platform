# -*- coding: utf-8 -*-
"""
Harbor API客户端
"""
import requests
from requests.auth import HTTPBasicAuth
import urllib3

# 禁用SSL警告（用于自签名证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class HarborClient:
    """Harbor API客户端"""

    def __init__(self, harbor_url, username, password, verify_ssl=False):
        """
        初始化Harbor客户端

        Args:
            harbor_url: Harbor地址/域名，如 hub.hzbxhd.com（无协议时自动补 https://）
            username: 用户名
            password: 密码
            verify_ssl: 是否验证SSL证书
        """
        if harbor_url and not harbor_url.startswith(('http://', 'https://')):
            harbor_url = 'https://' + harbor_url
        self.harbor_url = harbor_url.rstrip('/')
        self.auth = HTTPBasicAuth(username, password)
        self.verify = verify_ssl
        self.headers = {'Content-Type': 'application/json'}

    def _request(self, method, path, **kwargs):
        """发送请求"""
        url = f"{self.harbor_url}{path}"
        kwargs.setdefault('auth', self.auth)
        kwargs.setdefault('headers', self.headers)
        kwargs.setdefault('verify', self.verify)
        kwargs.setdefault('timeout', 30)

        response = requests.request(method, url, **kwargs)
        return response

    def get_projects(self, page=1, page_size=10, q=None):
        """
        获取项目列表

        Args:
            page: 页码
            page_size: 每页数量
            q: 查询条件，如 "name=test"
        """
        params = {
            'page': page,
            'page_size': page_size
        }
        if q:
            params['q'] = q

        response = self._request('GET', '/api/v2.0/projects', params=params)
        return response.json()

    def get_project(self, project_name):
        """
        获取单个项目信息

        Args:
            project_name: 项目名称
        """
        response = self._request('GET', f'/api/v2.0/projects/{project_name}')
        if response.status_code == 200:
            return response.json()
        return None

    def create_project(self, project_name, public=True, metadata=None):
        """
        创建项目

        Args:
            project_name: 项目名称
            public: 是否公开
            metadata: 元数据，如 {"auto_scan": "true"}
        """
        meta = {'public': 'true' if public else 'false'}
        if metadata:
            meta.update(metadata)
        data = {
            'project_name': project_name,
            'metadata': meta
        }

        response = self._request('POST', '/api/v2.0/projects', json=data)
        return {
            'success': response.status_code in [200, 201],
            'status_code': response.status_code,
            'message': 'Project created successfully' if response.status_code in [200, 201] else response.text
        }

    def update_project_metadata(self, project_name, metadata):
        """
        更新项目元数据

        Args:
            project_name: 项目名称
            metadata: 要更新的元数据字典
        """
        response = self._request('POST',
            f'/api/v2.0/projects/{project_name}/metadatas/',
            json=metadata)
        return {
            'success': response.status_code in [200, 201],
            'status_code': response.status_code
        }

    def delete_repository(self, project_name, repository_name):
        """
        删除仓库（会级联删除其中的所有制品）

        Args:
            project_name: 项目名称
            repository_name: 仓库名称
        """
        response = self._request('DELETE',
            f'/api/v2.0/projects/{project_name}/repositories/{repository_name}')
        return {
            'success': response.status_code in [200, 204],
            'status_code': response.status_code
        }

    def delete_project(self, project_name, force=True):
        """
        删除项目，先清理项目下所有仓库再删除项目

        Args:
            project_name: 项目名称
            force: 是否强制清理（默认True，先删仓库再删项目）
        """
        if force:
            page = 1
            deleted_repos = []
            while True:
                repos = self.get_repositories(project_name, page=page, page_size=50)
                if not repos:
                    break
                for repo in repos:
                    repo_name = repo.get('name', '')
                    # repo name 可能是 project_name/repo_name 格式
                    if '/' in repo_name:
                        repo_name = repo_name.split('/', 1)[1]
                    import urllib.parse
                    encoded_name = urllib.parse.quote(repo_name, safe='')
                    result = self.delete_repository(project_name, encoded_name)
                    if result['success']:
                        deleted_repos.append(repo_name)
                    else:
                        print(f"[Harbor] 删除仓库失败: {repo_name}, 状态码: {result.get('status_code')}")
                page += 1
            if deleted_repos:
                print(f"[Harbor] 已清理 {len(deleted_repos)} 个仓库")

        response = self._request('DELETE', f'/api/v2.0/projects/{project_name}')
        return {
            'success': response.status_code in [200, 204],
            'status_code': response.status_code
        }

    def get_repositories(self, project_name, page=1, page_size=10):
        """
        获取项目下的仓库列表

        Args:
            project_name: 项目名称
        """
        params = {
            'page': page,
            'page_size': page_size
        }
        response = self._request('GET', f'/api/v2.0/projects/{project_name}/repositories', params=params)
        return response.json()

    def get_artifacts(self, project_name, repository_name, page=1, page_size=10):
        """
        获取镜像制品列表

        Args:
            project_name: 项目名称
            repository_name: 仓库名称
        """
        params = {
            'page': page,
            'page_size': page_size
        }
        response = self._request('GET',
            f'/api/v2.0/projects/{project_name}/repositories/{repository_name}/artifacts',
            params=params)
        return response.json()

    def create_retention_policy(self, project_name_or_id, keep_recent=3, cron='0 0 * * * *'):
        """
        创建标签保留策略并关联到项目
        使用 Harbor v2.0 顶层 /retentions API

        Args:
            project_name_or_id: 项目名称或ID
            keep_recent: 保留最近N个版本
            cron: 定时执行的cron表达式，默认每小时
        """
        # 1. 创建保留策略
        data = {
            'algorithm': 'or',
            'rules': [
                {
                    'disabled': False,
                    'action': 'retain',
                    'template': 'latestPushedK',
                    'params': {
                        'latestPushedK': keep_recent
                    },
                    'tag_selectors': [
                        {
                            'kind': 'doublestar',
                            'decoration': 'matches',
                            'pattern': '**'
                        }
                    ],
                    'scope_selectors': {
                        'repository': [
                            {
                                'kind': 'doublestar',
                                'decoration': 'repoMatches',
                                'pattern': '**'
                            }
                        ]
                    }
                }
            ],
            'trigger': {
                'kind': 'Schedule',
                'settings': {
                    'cron': cron
                }
            },
            'scope': {
                'level': 'project',
                'ref': project_name_or_id if isinstance(project_name_or_id, int) else 0
            }
        }

        response = self._request('POST', '/api/v2.0/retentions', json=data)
        if response.status_code not in [200, 201]:
            return {
                'success': False,
                'status_code': response.status_code,
                'message': response.text
            }

        # 从 Location 头提取 retention ID
        retention_id = None
        location = response.headers.get('Location', '')
        if location:
            parts = location.rstrip('/').split('/')
            retention_id = parts[-1]

        # 如果 scope 设置了 ref=project_id，Harbor 会自动关联
        # 否则需要手动设置项目 metadata 的 retention_id
        if retention_id and not isinstance(project_name_or_id, int):
            meta_result = self.update_project_metadata(
                project_name_or_id,
                {'retention_id': str(retention_id)}
            )
            if not meta_result['success']:
                print(f"[Harbor] 关联 retention_id 到项目失败: {meta_result.get('status_code')}")

        return {
            'success': True,
            'retention_id': retention_id,
            'status_code': response.status_code
        }

    def get_project_summary(self, project_name):
        """
        获取项目概览

        Args:
            project_name: 项目名称
        """
        response = self._request('GET', f'/api/v2.0/projects/{project_name}/summary')
        return response.json()
