# -*- coding: utf-8 -*-
"""
系统设置接口处理函数
"""
from flask import request
from core.db import db
from modules.system.models import Setting
from core.response import success_response, error_response
from core.security import require_permission
from modules.system.settings_groups import SETTING_GROUPS

# 不返回值的敏感字段
HIDDEN_FIELDS = ['nfs_ssh_pass', 'harbor_pass', 'k8s_ssh_pass', 'nginx_ssh_pass', 'mysql_default_pass', 'redis_pass', 'rabbitmq_pass', 'nacos_pass', 'authplatform_secret']

# 只读设置：不允许通过设置接口修改（如平台密钥，改动会导致所有 Agent 通讯失效）
READONLY_FIELDS = ['agent_comm_secret']


@require_permission('page:settings')
def list_settings():
    """获取设置；支持 ?type=deploy|nginx|middleware 按 settings.type 分组返回，缺省返回全部"""
    group = request.args.get('type', '')
    query = Setting.query
    if group:
        if group not in SETTING_GROUPS:
            return error_response('未知的 type，可选值: deploy/nginx/middleware', 400)
        query = query.filter(Setting.type == group)
    settings = query.all()
    result = {}
    for s in settings:
        if s.key in HIDDEN_FIELDS:
            result[s.key] = {
                'value': '******' if s.value else '',
                'description': s.description,
                'has_value': bool(s.value)
            }
        else:
            result[s.key] = {
                'value': s.value,
                'description': s.description
            }
    return success_response(result)


@require_permission('op:settings')
def update_settings():
    """
    更新设置（对比检查，只更新变化的字段）

    请求体:
    {
        "nfs_server": "172.16.0.13",
        "nfs_ssh_pass": "new_password",  // 密码字段：有值才更新
        ...
    }
    """
    data = request.json
    if not data:
        return error_response('参数不能为空', 400)

    updated = []
    skipped = []

    for key, new_value in data.items():
        setting = Setting.query.filter_by(key=key).first()
        if not setting:
            skipped.append({'key': key, 'reason': '设置项不存在'})
            continue

        if key in READONLY_FIELDS:
            skipped.append({'key': key, 'reason': '只读字段，不允许修改'})
            continue

        old_value = setting.value

        # 密码字段特殊处理
        if key in HIDDEN_FIELDS:
            # 密码字段：空值或占位符不更新
            if not new_value or new_value == '******':
                skipped.append({'key': key, 'reason': '密码未修改'})
                continue
            setting.value = new_value
            updated.append(key)
        else:
            # 普通字段：值相同则跳过
            if str(new_value) == str(old_value):
                skipped.append({'key': key, 'reason': '值未变化'})
                continue
            setting.value = str(new_value)
            updated.append(key)

    if updated:
        db.session.commit()

    return success_response({
        'updated': updated,
        'skipped': skipped,
        'updated_count': len(updated),
        'skipped_count': len(skipped)
    }, f'更新了 {len(updated)} 项设置')


@require_permission('op:settings')
def debug_settings():
    """调试：返回所有设置（包括密码）"""
    settings = Setting.query.all()
    result = {}
    for s in settings:
        result[s.key] = {
            'value': s.value,
            'description': s.description
        }
    return success_response(result)


@require_permission('op:settings')
def test_ssh():
    """测试SSH连接（从数据库读取密码）"""
    # 从数据库读取配置
    host = Setting.query.filter_by(key='nfs_server').first()
    port = Setting.query.filter_by(key='nfs_ssh_port').first()
    username = Setting.query.filter_by(key='nfs_ssh_user').first()
    password = Setting.query.filter_by(key='nfs_ssh_pass').first()

    host = host.value if host else ''
    port = int(port.value) if port else 22
    username = username.value if username else ''
    password = password.value if password else ''

    if not host or not username:
        return error_response('请先配置NFS服务器地址和SSH用户名', 400)
    if not password:
        return error_response('请先配置SSH密码', 400)

    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=10)

        stdin, stdout, stderr = ssh.exec_command('echo "SSH连接成功"')
        output = stdout.read().decode().strip()
        ssh.close()

        return success_response({'output': output}, 'SSH连接成功')
    except Exception as e:
        return error_response(f'SSH连接失败: {str(e)}', 500)


@require_permission('op:settings')
def test_k8s_ssh():
    """测试K8s Master SSH连接"""
    host = Setting.query.filter_by(key='k8s_master_ip').first()
    port = Setting.query.filter_by(key='nfs_ssh_port').first()
    username = Setting.query.filter_by(key='k8s_ssh_user').first()
    password = Setting.query.filter_by(key='k8s_ssh_pass').first()

    host = host.value if host else ''
    port = int(port.value) if port else 22
    username = username.value if username else 'root'
    password = password.value if password else ''

    if not host:
        return error_response('请先配置K8s Master地址', 400)
    if not username:
        return error_response('请先配置K8s Master SSH用户名', 400)
    if not password:
        return error_response('请先配置K8s Master SSH密码', 400)

    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=10)

        stdin, stdout, stderr = ssh.exec_command('kubectl version --short 2>/dev/null || kubectl version 2>/dev/null | head -5')
        output = stdout.read().decode().strip()
        ssh.close()

        return success_response({'output': output}, f'SSH连接成功，kubectl: {output}')
    except Exception as e:
        return error_response(f'SSH连接失败: {str(e)}', 500)


@require_permission('op:settings')
def test_nginx_ssh():
    """测试Nginx服务器 SSH连接"""
    host = Setting.query.filter_by(key='nginx_server').first()
    port = Setting.query.filter_by(key='nginx_ssh_port').first()
    username = Setting.query.filter_by(key='nginx_ssh_user').first()
    password = Setting.query.filter_by(key='nginx_ssh_pass').first()

    host = host.value if host else ''
    port = int(port.value) if port else 22
    username = username.value if username else 'root'
    password = password.value if password else ''

    if not host:
        return error_response('请先配置Nginx服务器地址', 400)
    if not username:
        return error_response('请先配置Nginx SSH用户名', 400)
    if not password:
        return error_response('请先配置Nginx SSH密码', 400)

    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=10)

        stdin, stdout, stderr = ssh.exec_command('nginx -v 2>&1 || echo "nginx not found"')
        output = stdout.read().decode().strip()
        ssh.close()

        return success_response({'output': output}, f'SSH连接成功，{output}')
    except Exception as e:
        return error_response(f'SSH连接失败: {str(e)}', 500)


@require_permission('op:settings')
def test_harbor():
    """测试Harbor连接（从数据库读取密码）"""
    # 从数据库读取配置
    url = Setting.query.filter_by(key='harbor_url').first()
    username = Setting.query.filter_by(key='harbor_user').first()
    password = Setting.query.filter_by(key='harbor_pass').first()

    url = url.value if url else ''
    username = username.value if username else ''
    password = password.value if password else ''

    if not url or not username:
        return error_response('请先配置Harbor地址和用户名', 400)
    if not password:
        return error_response('请先配置Harbor密码', 400)

    try:
        import requests
        from requests.auth import HTTPBasicAuth

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        response = requests.get(
            f'{url.rstrip("/")}/api/v2.0/systeminfo',
            auth=HTTPBasicAuth(username, password),
            verify=False,
            timeout=10
        )

        if response.status_code == 200:
            info = response.json()
            version = info.get('harbor_version') or info.get('version') or 'unknown'
            return success_response({
                'harbor_version': version,
                'auth_mode': info.get('auth_mode', 'unknown')
            }, 'Harbor连接成功')
        else:
            return error_response(f'Harbor连接失败: HTTP {response.status_code}', 500)
    except Exception as e:
        return error_response(f'Harbor连接失败: {str(e)}', 500)
