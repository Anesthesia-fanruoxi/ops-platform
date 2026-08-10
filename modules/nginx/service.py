# -*- coding: utf-8 -*-
"""
Nginx远程配置文件同步服务
通过SSH在Nginx服务器上进行文件操作（MD5校验+增量同步）
"""
import os
import hashlib
import paramiko


class NginxService:
    """Nginx远程配置文件同步服务"""

    def __init__(self, host=None, port=None, username=None, password=None):
        from modules.system.models import Setting

        def _get_setting(key, default):
            try:
                s = Setting.query.filter_by(key=key).first()
                return s.value if s and s.value else default
            except Exception:
                return default

        self.host = host or _get_setting('nginx_server', '')
        self.port = int(port or _get_setting('nginx_ssh_port', '') or 22)
        self.username = username or _get_setting('nginx_ssh_user', '')
        self.password = password or _get_setting('nginx_ssh_pass', '')

    def _get_ssh_client(self):
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=10
        )
        return ssh

    def test_connection(self):
        """测试SSH连接"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command("echo ok", timeout=5)
            result = stdout.read().decode().strip()
            return result == 'ok'
        finally:
            ssh.close()

    def remote_directory_exists(self, remote_path):
        """检查远程目录是否存在"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"test -d {remote_path} && echo 'exists'")
            output = stdout.read().decode().strip()
            return output == 'exists'
        finally:
            ssh.close()

    def remote_file_exists(self, remote_path):
        """检查远程文件是否存在"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"test -f {remote_path} && echo 'exists'")
            output = stdout.read().decode().strip()
            return output == 'exists'
        finally:
            ssh.close()

    def delete_remote_file(self, remote_path):
        """删除远程文件

        Returns:
            bool: 是否成功
        """
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"rm -f {remote_path}")
            exit_code = stdout.channel.recv_exit_status()
            return exit_code == 0
        finally:
            ssh.close()

    def exec_command(self, cmd, timeout=60):
        """执行远程 SSH 命令

        Returns:
            dict: {'stdout': str, 'stderr': str, 'exit_code': int}
        """
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            return {
                'stdout': stdout.read().decode().strip(),
                'stderr': stderr.read().decode().strip(),
                'exit_code': exit_code
            }
        finally:
            ssh.close()

    def move_remote_file(self, src, dst):
        """移动远程文件

        Returns:
            bool: 是否成功
        """
        r = self.exec_command(f'mv {src} {dst}')
        return r['exit_code'] == 0

    def push_config(self, content, remote_file_path):
        """将配置文件内容推送到远程服务器

        Args:
            content: 配置文件内容字符串
            remote_file_path: 远程文件完整路径

        Returns:
            bool: 是否成功
        """
        ssh = self._get_ssh_client()
        try:
            sftp = ssh.open_sftp()
            try:
                with sftp.file(remote_file_path, 'w') as f:
                    f.write(content)
                return True
            finally:
                sftp.close()
        finally:
            ssh.close()

    def reload_nginx(self):
        """测试配置并 reload Nginx

        Returns:
            tuple: (success: bool, message: str)
        """
        ssh = self._get_ssh_client()
        try:
            # 先 test 配置语法
            stdin, stdout, stderr = ssh.exec_command('nginx -t', timeout=15)
            exit_code = stdout.channel.recv_exit_status()
            test_out = stdout.read().decode().strip()
            test_err = stderr.read().decode().strip()
            if exit_code != 0:
                return False, f'配置语法检测失败:\n{test_err or test_out}'

            # reload
            stdin, stdout, stderr = ssh.exec_command('nginx -s reload', timeout=15)
            exit_code = stdout.channel.recv_exit_status()
            reload_err = stderr.read().decode().strip()
            if exit_code != 0:
                return False, f'Nginx reload 失败:\n{reload_err}'

            return True, 'Nginx 配置已更新并 reload 成功'
        finally:
            ssh.close()

    def sync_directory(self, remote_path, local_path, log=None):
        """文件级强一致同步

        原则: 远程为主、本地为辅
        1. 远程获取所有文件的 MD5
        2. 本地计算已有文件 MD5
        3. 仅下载新增/变更的文件
        4. 删除远程已不存在的本地文件

        Args:
            remote_path: 远程目录路径
            local_path: 本地目录路径
            log: 日志回调 log(level, message)

        Returns:
            dict: {added:[], updated:[], deleted:[], unchanged:int}
        """
        def _log(level, msg):
            if log:
                log(level, msg)

        # 1. 获取远程文件 MD5 列表
        _log('INFO', f'获取远程文件列表: {remote_path}')
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(
                f"find {remote_path} -maxdepth 1 -type f -name '*.conf' -exec md5sum {{}} +",
                timeout=60
            )
            exit_code = stdout.channel.recv_exit_status()
            raw = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            if exit_code != 0 and err:
                _log('WARN', f'远程md5sum执行异常: {err}')
        finally:
            ssh.close()

        # 解析远程文件: {文件名: md5}
        remote_files = {}
        if raw:
            for line in raw.split('\n'):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    md5_hash = parts[0]
                    file_name = os.path.basename(parts[1])
                    remote_files[file_name] = md5_hash

        _log('INFO', f'远程文件数: {len(remote_files)}')

        # 2. 计算本地文件 MD5
        local_files = {}
        if os.path.isdir(local_path):
            for fname in os.listdir(local_path):
                fpath = os.path.join(local_path, fname)
                if os.path.isfile(fpath):
                    local_files[fname] = self._file_md5(fpath)

        _log('INFO', f'本地文件数: {len(local_files)}')

        # 3. 三路对比
        added = []
        updated = []
        unchanged = 0
        remote_set = set(remote_files.keys())
        local_set = set(local_files.keys())

        to_download = []
        for file_name, remote_md5 in remote_files.items():
            if file_name not in local_set:
                to_download.append(file_name)
                added.append(file_name)
            elif local_files[file_name] != remote_md5:
                to_download.append(file_name)
                updated.append(file_name)
            else:
                unchanged += 1

        # 4. 下载变更文件
        if to_download:
            _log('INFO', f'需要下载: {len(to_download)} 个文件')
            ssh = self._get_ssh_client()
            try:
                sftp = ssh.open_sftp()
                try:
                    os.makedirs(local_path, exist_ok=True)
                    for file_name in to_download:
                        remote_file = f"{remote_path}/{file_name}"
                        local_file = os.path.join(local_path, file_name)
                        sftp.get(remote_file, local_file)
                        _log('INFO', f'  下载: {file_name}')
                finally:
                    sftp.close()
            finally:
                ssh.close()
        else:
            _log('INFO', '无需下载，文件均一致')

        # 5. 删除远程已不存在的本地文件
        deleted = []
        to_delete = local_set - remote_set
        for file_name in to_delete:
            local_file = os.path.join(local_path, file_name)
            try:
                os.remove(local_file)
                deleted.append(file_name)
                _log('INFO', f'  删除: {file_name}')
            except Exception as e:
                _log('WARN', f'  删除失败: {file_name} - {e}')

        _log('INFO', f'同步完成: 新增{len(added)}个, 更新{len(updated)}个, 删除{len(deleted)}个, 跳过{unchanged}个')

        return {
            'added': added,
            'updated': updated,
            'deleted': deleted,
            'unchanged': unchanged
        }

    @staticmethod
    def _file_md5(file_path):
        """计算本地文件 MD5"""
        h = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

