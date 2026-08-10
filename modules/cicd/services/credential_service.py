# -*- coding: utf-8 -*-
"""
凭据服务：AES 加解密、git 凭据测试、构建时解密下发
"""
import base64
import subprocess
import tempfile
import os

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from core.db import db
from modules.system.models import Setting
from modules.cicd.models import GitCredential


def _get_aes_key():
    """从 Setting 的 default_encrypted 盐派生 32 字节 AES 密钥"""
    setting = Setting.query.filter_by(key='default_encrypted').first()
    salt = setting.value if setting else 'default_salt_key_32b'
    # 取前 32 字节作为密钥（UTF-8 编码后截断/填充）
    key_bytes = salt.encode('utf-8')[:32]
    if len(key_bytes) < 32:
        key_bytes = key_bytes.ljust(32, b'\0')
    return key_bytes


def encrypt_secret(plaintext):
    """AES-CBC 加密，返回 base64 密文"""
    if not plaintext:
        return ''
    key = _get_aes_key()
    cipher = AES.new(key, AES.MODE_CBC)
    iv = cipher.iv
    encrypted = cipher.encrypt(pad(plaintext.encode('utf-8'), AES.block_size))
    # iv + 密文 一起 base64
    return base64.b64encode(iv + encrypted).decode('ascii')


def decrypt_secret(ciphertext):
    """AES-CBC 解密，输入 base64 密文，返回明文"""
    if not ciphertext:
        return ''
    try:
        key = _get_aes_key()
        raw = base64.b64decode(ciphertext)
        iv = raw[:16]
        encrypted = raw[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(encrypted), AES.block_size).decode('utf-8')
    except Exception:
        return ''


def test_git_credential(credential_id):
    """用 git ls-remote 验证凭据有效性，返回 (success, message)"""
    cred = GitCredential.query.get(credential_id)
    if not cred:
        return False, '凭据不存在'

    # 需要一个关联了该凭据的模板才能拿到 git_url；这里直接用凭据构造测试
    # 简化：仅验证凭据格式可解密
    secret = decrypt_secret(cred.secret)
    if cred.type in ('password', 'token') and not secret:
        return False, '凭据密钥解密失败或为空'

    return True, '凭据格式有效（解密成功）'


def test_git_connection(git_url, credential_id):
    """用 git ls-remote 测试实际连通性"""
    cred = GitCredential.query.get(credential_id) if credential_id else None
    remote_url, env, key_file = _build_git_access(git_url, cred)
    try:
        result = subprocess.run(
            ['git', '-c', 'http.sslVerify=false', 'ls-remote', '--heads', remote_url],
            capture_output=True, encoding='utf-8', errors='replace', timeout=15, env=env
        )
        if result.returncode == 0:
            return True, '连接成功'
        return False, (result.stderr or '').strip()[:200] or '连接失败'
    except subprocess.TimeoutExpired:
        return False, '连接超时（15s）'
    except FileNotFoundError:
        return False, '服务器未安装 git'
    except Exception as e:
        return False, str(e)[:200]
    finally:
        if key_file:
            try:
                os.remove(key_file)
            except Exception:
                pass


def _ssh_to_https(git_url):
    """将 SSH 格式的 git 地址转换为 HTTPS 格式（SSH 端口非 HTTPS 端口，转换时丢弃）"""
    import re
    # git@host:group/project.git
    m = re.match(r'^git@([^:]+):(.+)$', git_url)
    if m:
        return f'https://{m.group(1)}/{m.group(2)}'
    # ssh://git@host:port/group/project.git（port 是 SSH 端口，丢弃后用默认 HTTPS 端口）
    m = re.match(r'^ssh://git@([^/:]+)(:\d+)?/(.+)$', git_url)
    if m:
        return f'https://{m.group(1)}/{m.group(3)}'
    return git_url


def _write_temp_key(key_content):
    """将 SSH 私钥内容写入临时文件（0600 权限），返回文件路径"""
    try:
        fd, path = tempfile.mkstemp(prefix='git_key_', suffix='.pem')
        with os.fdopen(fd, 'w') as f:
            f.write(key_content)
            if not key_content.endswith('\n'):
                f.write('\n')
        os.chmod(path, 0o600)
        return path
    except Exception:
        return None


def _build_git_access(git_url, cred):
    """根据凭据类型构造 git 访问参数，返回 (remote_url, env, key_file)。
    - ssh_key：保持原 SSH 地址，通过 GIT_SSH_COMMAND 指定临时密钥文件
    - token/password：转 HTTPS 并将凭据注入 URL
    调用方负责在 finally 中删除 key_file。
    """
    secret = decrypt_secret(cred.secret) if cred else ''
    username = cred.username if cred else ''
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    key_file = None

    if cred and cred.type == 'ssh_key' and secret:
        remote_url = git_url
        key_file = _write_temp_key(secret)
        if key_file:
            # Windows 路径反斜杠会被 ssh 当转义符吃掉，统一转正斜杠并加引号
            key_path = key_file.replace('\\', '/')
            env['GIT_SSH_COMMAND'] = (
                f'ssh -i "{key_path}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
            )
    else:
        remote_url = _ssh_to_https(git_url)
        if cred and cred.type == 'token' and secret:
            remote_url = remote_url.replace('https://', f'https://{secret}@')
        elif cred and cred.type == 'password' and username and secret:
            remote_url = remote_url.replace('https://', f'https://{username}:{secret}@')
    return remote_url, env, key_file


def list_git_branches(git_url, credential_id):
    """用 git ls-remote --heads 获取远程分支列表，返回 (branches, error_msg)"""
    cred = GitCredential.query.get(credential_id) if credential_id else None
    remote_url, env, key_file = _build_git_access(git_url, cred)
    if cred and cred.type == 'ssh_key' and not key_file:
        return [], 'SSH 私钥写入临时文件失败'

    try:
        result = subprocess.run(
            ['git', '-c', 'http.sslVerify=false', 'ls-remote', '--heads', remote_url],
            capture_output=True, encoding='utf-8', errors='replace', timeout=15, env=env
        )
        if result.returncode != 0:
            return [], (result.stderr or '').strip()[:200] or '获取分支失败'
        branches = []
        for line in (result.stdout or '').strip().splitlines():
            # 格式: <sha>\trefs/heads/<branch>
            if '\t' in line and 'refs/heads/' in line:
                branches.append(line.split('refs/heads/', 1)[1])
        # 常用分支置顶
        priority = ['master', 'main', 'develop', 'release']
        branches.sort(key=lambda b: (priority.index(b) if b in priority else 99, b))
        return branches, ''
    except subprocess.TimeoutExpired:
        return [], '连接超时（15s）'
    except FileNotFoundError:
        return [], '服务器未安装 git'
    except Exception as e:
        return [], str(e)[:200]
    finally:
        if key_file:
            try:
                os.remove(key_file)
            except Exception:
                pass


def get_decrypted_credential(credential_id):
    """构建分发时解密凭据（仅内存中使用）"""
    cred = GitCredential.query.get(credential_id)
    if not cred:
        return None
    return {
        'type': cred.type,
        'username': cred.username,
        'secret': decrypt_secret(cred.secret),
    }
