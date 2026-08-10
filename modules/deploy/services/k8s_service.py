# -*- coding: utf-8 -*-
"""
K8s Master远程文件操作服务
通过SSH在K8s Master上进行文件操作（SCP上传/下载/移动/删除）和执行kubectl命令
"""
import os
import stat
import hashlib
import paramiko


class K8sService:
    """K8s Master远程文件操作服务"""

    def __init__(self, host=None, port=None, username=None, password=None):
        """
        初始化（优先从数据库读取配置）

        Args:
            host: K8s Master地址
            port: SSH端口
            username: SSH用户名
            password: SSH密码
        """
        from modules.system.models import Setting

        def _get_setting(key, default):
            try:
                s = Setting.query.filter_by(key=key).first()
                return s.value if s and s.value else default
            except Exception:
                return default

        self.host = host or _get_setting('k8s_master_ip', '')
        self.port = int(port or _get_setting('nfs_ssh_port', '') or 22)
        self.username = username or _get_setting('k8s_ssh_user', '')
        self.password = password or _get_setting('k8s_ssh_pass', '')

    def _get_ssh_client(self):
        """获取SSH客户端"""
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

    # ─── 通用命令执行 ─────────────────────────────────────

    def exec_command(self, cmd, timeout=None):
        """在K8s Master上执行命令

        Args:
            cmd: 要执行的命令（如 kubectl get pods）
            timeout: 命令超时秒数，None表示不限制

        Returns:
            dict: {exit_code, stdout, stderr}
        """
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            return {'exit_code': exit_code, 'stdout': out, 'stderr': err}
        finally:
            ssh.close()

    # ─── 远程目录/文件操作 ─────────────────────────────────

    def remote_directory_exists(self, remote_path):
        """检查远程目录是否存在"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"test -d {remote_path} && echo 'exists'")
            output = stdout.read().decode().strip()
            return output == 'exists'
        finally:
            ssh.close()

    def list_remote_dirs(self, remote_path):
        """列出远程目录下的子目录"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"ls -1 {remote_path}")
            output = stdout.read().decode().strip()
            if not output:
                return []
            return [line for line in output.split('\n') if line]
        finally:
            ssh.close()

    def list_remote_files(self, remote_path, pattern='*.yaml'):
        """列出远程目录下的文件（支持通配符）"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"ls -1 {remote_path}/{pattern} 2>/dev/null")
            output = stdout.read().decode().strip()
            if not output:
                return []
            return [os.path.basename(line.strip()) for line in output.split('\n') if line.strip()]
        finally:
            ssh.close()

    def download_directory(self, remote_path, local_path):
        """递归下载远程目录到本地（覆盖）"""
        ssh = self._get_ssh_client()
        try:
            sftp = ssh.open_sftp()
            try:
                self._download_recursive(sftp, remote_path, local_path)
            finally:
                sftp.close()
        finally:
            ssh.close()

    def _download_recursive(self, sftp, remote_path, local_path):
        """递归下载辅助方法"""
        try:
            os.makedirs(local_path, exist_ok=True)
            for item in sftp.listdir_attr(remote_path):
                remote_item = f"{remote_path}/{item.filename}"
                local_item = os.path.join(local_path, item.filename)
                if stat.S_ISDIR(item.st_mode):
                    self._download_recursive(sftp, remote_item, local_item)
                else:
                    sftp.get(remote_item, local_item)
        except IOError:
            pass

    def upload_directory(self, local_path, remote_path):
        """递归上传本地目录到远程"""
        ssh = self._get_ssh_client()
        try:
            sftp = ssh.open_sftp()
            try:
                self._upload_recursive(sftp, local_path, remote_path)
            finally:
                sftp.close()
        finally:
            ssh.close()

    def _upload_recursive(self, sftp, local_path, remote_path):
        """递归上传辅助方法"""
        try:
            sftp.mkdir(remote_path)
        except IOError:
            pass
        for item in os.listdir(local_path):
            local_item = os.path.join(local_path, item)
            remote_item = f"{remote_path}/{item}"
            if os.path.isdir(local_item):
                self._upload_recursive(sftp, local_item, remote_item)
            else:
                sftp.put(local_item, remote_item)

    def move_directory(self, source_path, dest_path):
        """远程移动目录（用于回收/恢复）"""
        ssh = self._get_ssh_client()
        try:
            # 确保目标父目录存在
            dest_parent = os.path.dirname(dest_path)
            ssh.exec_command(f"mkdir -p {dest_parent}")
            # 移动目录
            stdin, stdout, stderr = ssh.exec_command(f"mv {source_path} {dest_path}")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                error = stderr.read().decode()
                raise Exception(f"移动目录失败: {error}")
            return True
        finally:
            ssh.close()

    # ─── 文件级强一致同步 ─────────────────────────────────────

    def sync_directory(self, remote_path, local_path, log=None):
        """文件级强一致同步（递归）

        原则: 远程为主、本地为辅
        1. 远程获取所有文件的 MD5 (find ... -exec md5sum)
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
                f"find {remote_path} -type f -exec md5sum {{}} +",
                timeout=60
            )
            exit_code = stdout.channel.recv_exit_status()
            raw = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            if exit_code != 0 and err:
                _log('WARN', f'远程md5sum执行异常: {err}')
        finally:
            ssh.close()

        # 解析远程文件: {相对路径: md5}
        remote_files = {}
        if raw:
            for line in raw.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # 格式: md5hash  /absolute/path
                parts = line.split(None, 1)
                if len(parts) == 2:
                    md5_hash = parts[0]
                    abs_path = parts[1]
                    rel_path = os.path.relpath(abs_path, remote_path).replace('\\', '/')
                    remote_files[rel_path] = md5_hash

        _log('INFO', f'远程文件数: {len(remote_files)}')

        # 2. 计算本地文件 MD5: {相对路径: md5}
        local_files = {}
        if os.path.isdir(local_path):
            for root, dirs, files in os.walk(local_path):
                for fname in files:
                    abs_path = os.path.join(root, fname)
                    rel_path = os.path.relpath(abs_path, local_path).replace('\\', '/')
                    local_files[rel_path] = self._file_md5(abs_path)

        _log('INFO', f'本地文件数: {len(local_files)}')

        # 3. 三路对比
        added = []
        updated = []
        unchanged = 0
        remote_set = set(remote_files.keys())
        local_set = set(local_files.keys())

        # 需要下载的文件: 远程新增 + 远程变更
        to_download = []
        for rel_path, remote_md5 in remote_files.items():
            if rel_path not in local_set:
                to_download.append(rel_path)
                added.append(rel_path)
            elif local_files[rel_path] != remote_md5:
                to_download.append(rel_path)
                updated.append(rel_path)
            else:
                unchanged += 1

        # 4. 下载变更文件
        if to_download:
            _log('INFO', f'需要下载: {len(to_download)} 个文件')
            ssh = self._get_ssh_client()
            try:
                sftp = ssh.open_sftp()
                try:
                    for rel_path in to_download:
                        remote_file = f"{remote_path}/{rel_path}"
                        local_file = os.path.join(local_path, rel_path.replace('/', os.sep))
                        os.makedirs(os.path.dirname(local_file), exist_ok=True)
                        sftp.get(remote_file, local_file)
                        _log('INFO', f'  下载: {rel_path}')
                finally:
                    sftp.close()
            finally:
                ssh.close()
        else:
            _log('INFO', '无需下载，文件均一致')

        # 5. 删除远程已不存在的本地文件
        deleted = []
        to_delete = local_set - remote_set
        for rel_path in to_delete:
            local_file = os.path.join(local_path, rel_path.replace('/', os.sep))
            try:
                os.remove(local_file)
                deleted.append(rel_path)
                _log('INFO', f'  删除: {rel_path}')
                # 尝试清理空父目录
                parent = os.path.dirname(local_file)
                while parent != local_path:
                    if os.path.isdir(parent) and not os.listdir(parent):
                        os.rmdir(parent)
                        parent = os.path.dirname(parent)
                    else:
                        break
            except Exception as e:
                _log('WARN', f'  删除失败: {rel_path} - {e}')

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

    def remove_directory(self, remote_path):
        """删除远程目录"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"rm -rf {remote_path}")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                error = stderr.read().decode()
                raise Exception(f"删除目录失败: {error}")
            return True
        finally:
            ssh.close()
