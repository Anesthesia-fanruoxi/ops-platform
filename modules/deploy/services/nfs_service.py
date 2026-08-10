# -*- coding: utf-8 -*-
"""
NFS远程目录管理服务
通过SSH在NFS服务器上创建目录
"""
import paramiko


def _get_mount(key):
    """读取 NFS 挂载目录设置；未配置返回空"""
    from modules.system.settings_service import get_setting
    return get_setting(key, '')


class NFSService:
    """NFS远程目录管理服务"""

    def __init__(self, host=None, port=None, username=None, password=None):
        """
        初始化（优先从数据库读取配置，回退到环境变量/默认值）

        Args:
            host: NFS服务器地址
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

        self.host = host or _get_setting('nfs_server', '')
        self.port = int(port or _get_setting('nfs_ssh_port', '') or 22)
        self.username = username or _get_setting('nfs_ssh_user', '')
        self.password = password or _get_setting('nfs_ssh_pass', '')

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

    def create_directory(self, remote_path):
        """创建远程目录"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {remote_path}")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                error = stderr.read().decode()
                raise Exception(f"Failed to create directory: {error}")
            return True
        finally:
            ssh.close()

    def directory_exists(self, remote_path):
        """检查远程目录是否存在"""
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(f"test -d {remote_path} && echo 'exists'")
            output = stdout.read().decode().strip()
            return output == 'exists'
        finally:
            ssh.close()

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

    def create_project_dirs(self, project_name, env_name, services):
        """
        为项目创建所有必要的NFS目录

        Args:
            project_name: 项目名称
            env_name: 环境名称
            services: 服务列表

        Returns:
            dict: 创建结果
        """
        logs_mount = _get_mount('nfs_logs_mount')
        data_mount = _get_mount('nfs_data_mount')
        datastorg_mount = _get_mount('nfs_datastorg_mount')

        created_dirs = []
        skipped_dirs = []
        errors = []

        print(f"\n[部署] 开始创建NFS目录: {project_name}-{env_name}")

        # 1. 创建服务日志目录
        log_count = 0
        for service in services:
            service_name = service.get('name', service.get('app_name', ''))
            path = f"{logs_mount}/{project_name}-{env_name}/{project_name}-{service_name}"
            try:
                if self.directory_exists(path):
                    skipped_dirs.append({'path': path, 'type': 'log'})
                else:
                    self.create_directory(path)
                    created_dirs.append({'path': path, 'type': 'log'})
                log_count += 1
            except Exception as e:
                errors.append({'path': path, 'error': str(e)})
        print(f"[部署] 服务日志目录创建完成: {logs_mount}/{project_name}-{env_name}, 包含子目录 {log_count} 个")

        # 2. 创建公共目录
        template_path = f"{data_mount}/{project_name}/{env_name}/template"
        try:
            if self.directory_exists(template_path):
                skipped_dirs.append({'path': template_path, 'type': 'common'})
            else:
                self.create_directory(template_path)
                created_dirs.append({'path': template_path, 'type': 'common'})
            print(f"[部署] 模板目录创建完成: {template_path}")
        except Exception as e:
            errors.append({'path': template_path, 'error': str(e)})

        upload_path = f"{data_mount}/{project_name}/{env_name}/upload/public"
        try:
            if self.directory_exists(upload_path):
                skipped_dirs.append({'path': upload_path, 'type': 'common'})
            else:
                self.create_directory(upload_path)
                created_dirs.append({'path': upload_path, 'type': 'common'})
            print(f"[部署] 上传目录创建完成: {upload_path}")
        except Exception as e:
            errors.append({'path': upload_path, 'error': str(e)})

        key_path = f"{data_mount}/{project_name}/{env_name}/key"
        try:
            if self.directory_exists(key_path):
                skipped_dirs.append({'path': key_path, 'type': 'common'})
            else:
                self.create_directory(key_path)
                created_dirs.append({'path': key_path, 'type': 'common'})
            print(f"[部署] 密钥目录创建完成: {key_path}")
        except Exception as e:
            errors.append({'path': key_path, 'error': str(e)})

        yiqianbao_path = f"{data_mount}/{project_name}/{env_name}/yiqianbao"
        try:
            if self.directory_exists(yiqianbao_path):
                skipped_dirs.append({'path': yiqianbao_path, 'type': 'common'})
            else:
                self.create_directory(yiqianbao_path)
                created_dirs.append({'path': yiqianbao_path, 'type': 'common'})
            print(f"[部署] 易钱包目录创建完成: {yiqianbao_path}")
        except Exception as e:
            errors.append({'path': yiqianbao_path, 'error': str(e)})

        web_path = f"{data_mount}/{project_name}/{env_name}/web"
        try:
            if self.directory_exists(web_path):
                skipped_dirs.append({'path': web_path, 'type': 'common'})
            else:
                self.create_directory(web_path)
                created_dirs.append({'path': web_path, 'type': 'common'})
            print(f"[部署] Web目录创建完成: {web_path}")
        except Exception as e:
            errors.append({'path': web_path, 'error': str(e)})

        ops_path = f"{data_mount}/ops/{project_name}-{env_name}"
        try:
            if self.directory_exists(ops_path):
                skipped_dirs.append({'path': ops_path, 'type': 'common'})
            else:
                self.create_directory(ops_path)
                created_dirs.append({'path': ops_path, 'type': 'common'})
            print(f"[部署] 运维目录创建完成: {ops_path}")
        except Exception as e:
            errors.append({'path': ops_path, 'error': str(e)})

        # 3. 创建中间件目录
        redis_path = f"{datastorg_mount}/{project_name}/{env_name}/redis"
        try:
            if self.directory_exists(redis_path):
                skipped_dirs.append({'path': redis_path, 'type': 'middleware'})
            else:
                self.create_directory(redis_path)
                created_dirs.append({'path': redis_path, 'type': 'middleware'})
            print(f"[部署] Redis数据目录创建完成: {redis_path}")
        except Exception as e:
            errors.append({'path': redis_path, 'error': str(e)})

        nacos_path = f"{datastorg_mount}/{project_name}/{env_name}/nacos"
        try:
            if self.directory_exists(nacos_path):
                skipped_dirs.append({'path': nacos_path, 'type': 'middleware'})
            else:
                self.create_directory(nacos_path)
                created_dirs.append({'path': nacos_path, 'type': 'middleware'})
            print(f"[部署] Nacos数据目录创建完成: {nacos_path}")
        except Exception as e:
            errors.append({'path': nacos_path, 'error': str(e)})

        print(f"[部署] NFS目录创建完成: {len(created_dirs)} 个成功, {len(skipped_dirs)} 个跳过, {len(errors)} 个失败")

        return {
            'project': f"{project_name}-{env_name}",
            'created': len(created_dirs),
            'skipped': len(skipped_dirs),
            'failed': len(errors),
            'dirs': created_dirs,
            'skipped_dirs': skipped_dirs,
            'errors': errors
        }

    def check_project_dirs(self, project_name, env_name, services):
        """检查项目目录是否存在"""
        logs_mount = _get_mount('nfs_logs_mount')
        data_mount = _get_mount('nfs_data_mount')
        datastorg_mount = _get_mount('nfs_datastorg_mount')

        dirs_to_check = []
        for service in services:
            service_name = service.get('name', service.get('app_name', ''))
            dirs_to_check.append({'path': f"{logs_mount}/{project_name}-{env_name}/{project_name}-{service_name}", 'desc': f"Service log: {service_name}"})

        dirs_to_check.extend([
            {'path': f"{data_mount}/{project_name}/{env_name}/template", 'desc': 'Template'},
            {'path': f"{data_mount}/{project_name}/{env_name}/upload/public", 'desc': 'Upload'},
            {'path': f"{data_mount}/{project_name}/{env_name}/key", 'desc': 'Key'},
            {'path': f"{data_mount}/{project_name}/{env_name}/yiqianbao", 'desc': 'Yiqianbao'},
            {'path': f"{data_mount}/{project_name}/{env_name}/web", 'desc': 'Web'},
            {'path': f"{data_mount}/ops/{project_name}-{env_name}", 'desc': 'Ops'},
            {'path': f"{datastorg_mount}/{project_name}/{env_name}/redis", 'desc': 'Redis'},
            {'path': f"{datastorg_mount}/{project_name}/{env_name}/nacos", 'desc': 'Nacos'},
        ])

        results = []
        for item in dirs_to_check:
            exists = self.directory_exists(item['path'])
            results.append({'path': item['path'], 'desc': item['desc'], 'exists': exists})

        return results

    def copy_directory(self, source_path, dest_path):
        """复制远程目录内容到目标目录（复制 source/* 到 dest/，避免嵌套）"""
        ssh = self._get_ssh_client()
        try:
            # 确保目标目录存在
            stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {dest_path}")
            stdout.channel.recv_exit_status()
            # 复制源目录下的内容到目标目录（而非复制源目录本身）
            stdin, stdout, stderr = ssh.exec_command(f"cp -r {source_path}/* {dest_path}/")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                error = stderr.read().decode()
                raise Exception(f"Failed to copy directory: {error}")
            return True
        finally:
            ssh.close()

    def find_pvc_dir(self, base_path, pattern):
        """在NFS服务器上查找匹配模式的PVC目录

        Args:
            base_path: 基础路径（如 {datastorg_mount}/{project}/{env}/nacos）
            pattern: 匹配模式（如 {project}-{env}-middleware-mysql-data-mysql-0-pvc-*）

        Returns:
            找到的完整目录路径，未找到返回 None
        """
        ssh = self._get_ssh_client()
        try:
            cmd = f"ls -1d {base_path}/{pattern} 2>/dev/null | head -1"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            stdout.channel.recv_exit_status()
            result = stdout.read().decode().strip()
            return result if result else None
        finally:
            ssh.close()

    def sync_mysql_pvc_data(self, source_project, source_env, dest_project, dest_env):
        """MySQL PVC数据同步：从源环境选择性复制业务数据库到目标环境

        前提：目标环境的MySQL已启动并生成了PVC目录，然后已停止。
        PVC目录位于 /data/storageclass/ 下，命名格式为 {project}-{env}-middleware-mysql-data-mysql-0-pvc-*

        复制内容：
        - ibdata1（InnoDB系统表空间）
        - mysql.ibd（mysql系统库）
        - 所有非系统数据库目录（排除 mysql/performance_schema/sys/#innodb_temp）

        Args:
            source_project: 源项目名
            source_env: 源环境名
            dest_project: 目标项目名
            dest_env: 目标环境名
        """
        # PVC目录在 /data/storageclass/ 下，不在 nacos 子目录
        storageclass_base = '/data/storageclass'

        # PVC目录匹配模式
        source_pattern = f"{source_project}-{source_env}-middleware-mysql-data-mysql-0-pvc-*"
        dest_pattern = f"{dest_project}-{dest_env}-middleware-mysql-data-mysql-0-pvc-*"

        # 查找源PVC目录
        source_pvc = self.find_pvc_dir(storageclass_base, source_pattern)
        if not source_pvc:
            return {'success': False, 'message': f'源环境PVC目录不存在: {storageclass_base}/{source_pattern}'}

        # 查找目标PVC目录
        dest_pvc = self.find_pvc_dir(storageclass_base, dest_pattern)
        if not dest_pvc:
            return {'success': False, 'message': f'目标环境PVC目录不存在（需先启动MySQL生成PVC）: {storageclass_base}/{dest_pattern}'}

        print(f"[MySQL同步] 源PVC: {source_pvc}")
        print(f"[MySQL同步] 目标PVC: {dest_pvc}")

        # 系统目录排除列表
        system_dirs = {'mysql', 'performance_schema', 'sys', '#innodb_temp'}

        # 构建复制命令：复制固定文件 + 非系统数据库目录
        ssh = self._get_ssh_client()
        try:
            copied_count = 0

            # 1. 复制 ibdata1
            for f in ['ibdata1', 'mysql.ibd']:
                cmd = f"test -f {source_pvc}/{f} && cp -f {source_pvc}/{f} {dest_pvc}/{f} && echo OK"
                stdin, stdout, stderr = ssh.exec_command(cmd)
                exit_code = stdout.channel.recv_exit_status()
                result = stdout.read().decode().strip()
                if result == 'OK':
                    copied_count += 1
                    print(f"[MySQL同步] 复制文件: {f}")
                else:
                    print(f"[MySQL同步] 跳过文件: {f}（源不存在）")

            # 2. 复制业务数据库目录（排除系统目录）
            cmd = f"ls -1 {source_pvc}/"
            stdin, stdout, stderr = ssh.exec_command(cmd)
            stdout.channel.recv_exit_status()
            entries = stdout.read().decode().strip().split('\n')

            for entry in entries:
                entry = entry.strip()
                if not entry or entry in system_dirs:
                    continue
                if entry.startswith('#') or entry.startswith('ib') or entry.startswith('undo') or entry.startswith('mysql-bin') or entry.startswith('auto.cnf') or entry.endswith('.pem') or entry.endswith('.cnf') or entry.endswith('.index'):
                    continue
                # 检查是否是目录
                check_cmd = f"test -d {source_pvc}/{entry} && echo DIR"
                stdin, stdout, stderr = ssh.exec_command(check_cmd)
                stdout.channel.recv_exit_status()
                is_dir = stdout.read().decode().strip() == 'DIR'
                if is_dir:
                    cp_cmd = f"cp -rf {source_pvc}/{entry} {dest_pvc}/{entry}"
                    stdin, stdout, stderr = ssh.exec_command(cp_cmd)
                    exit_code = stdout.channel.recv_exit_status()
                    if exit_code == 0:
                        copied_count += 1
                        print(f"[MySQL同步] 复制数据库: {entry}")
                    else:
                        error = stderr.read().decode()
                        print(f"[MySQL同步] 复制失败: {entry}, {error}")

            return {
                'success': True,
                'source_pvc': source_pvc,
                'dest_pvc': dest_pvc,
                'copied_files': copied_count
            }
        finally:
            ssh.close()

    def copy_project_dirs(self, source_project, source_env, dest_project, dest_env, services):
        """复制环境数据：仅复制 Nacos 数据目录

        复制内容：
        - Nacos 数据目录（datastorg挂载点下的nacos目录）

        MySQL 数据复制不在本步骤处理，需在 k8s 阶段 MySQL 启动后停止再复制。
        """
        datastorg_mount = _get_mount('nfs_datastorg_mount')

        copied_dirs = []
        errors = []

        print(f"\n[部署] 开始复制数据: {source_project}-{source_env} -> {dest_project}-{dest_env}")

        # 复制 Nacos 数据目录
        source_nacos = f"{datastorg_mount}/{source_project}/{source_env}/nacos"
        dest_nacos = f"{datastorg_mount}/{dest_project}/{dest_env}/nacos"
        try:
            if self.directory_exists(source_nacos):
                self.copy_directory(source_nacos, dest_nacos)
                copied_dirs.append({
                    'source': source_nacos, 'dest': dest_nacos,
                    'type': 'middleware', 'desc': 'Nacos数据'
                })
                print(f"[部署] Nacos数据复制完成: {source_nacos} -> {dest_nacos}")
            else:
                print(f"[部署] 源Nacos目录不存在，跳过: {source_nacos}")
        except Exception as e:
            errors.append({'source': source_nacos, 'dest': dest_nacos, 'desc': 'Nacos数据', 'error': str(e)})
            print(f"[部署] Nacos数据复制失败: {e}")

        print(f"[部署] 数据复制完成: {len(copied_dirs)} 个成功, {len(errors)} 个失败")

        return {
            'source': f"{source_project}-{source_env}",
            'dest': f"{dest_project}-{dest_env}",
            'copied': len(copied_dirs),
            'failed': len(errors),
            'dirs': copied_dirs,
            'errors': errors
        }

    def move_directory(self, source_path, dest_path):
        """移动远程目录"""
        ssh = self._get_ssh_client()
        try:
            # 确保目标父目录存在
            parent_dir = '/'.join(dest_path.split('/')[:-1])
            stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {parent_dir}")
            stdout.channel.recv_exit_status()
            stdin, stdout, stderr = ssh.exec_command(f"mv {source_path} {dest_path}")
            exit_code = stdout.channel.recv_exit_status()
            if exit_code != 0:
                error = stderr.read().decode()
                raise Exception(f"Failed to move directory: {error}")
            return True
        finally:
            ssh.close()

    def recycle_project_dirs(self, project_name, env_name):
        """
        回收项目NFS目录：移动到回收站

        Args:
            project_name: 项目名称
            env_name: 环境名称

        Returns:
            dict: 回收结果
        """
        from datetime import datetime

        logs_mount = _get_mount('nfs_logs_mount')
        data_mount = _get_mount('nfs_data_mount')
        datastorg_mount = _get_mount('nfs_datastorg_mount')
        recycle_mount = '/data/recycle'

        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        env_full = f"{project_name}-{env_name}"
        recycle_dir = f"{recycle_mount}/{env_full}-{timestamp}"

        moved = []
        skipped = []
        errors = []

        print(f"\n[回收] 开始回收NFS目录: {env_full}")
        print(f"[回收] 回收站路径: {recycle_dir}")

        # 创建回收站目录
        try:
            self.create_directory(recycle_dir)
        except Exception as e:
            print(f"[回收] 创建回收站目录失败: {str(e)}")
            return {
                'project': env_full,
                'recycle_dir': recycle_dir,
                'moved': 0,
                'skipped': 0,
                'failed': 1,
                'errors': [{'path': recycle_dir, 'error': str(e)}]
            }

        # 需要回收的目录映射：源路径 -> 回收站子目录名
        dirs_to_recycle = [
            (f"{logs_mount}/{env_full}", 'logs'),
            (f"{data_mount}/{project_name}/{env_name}", 'project'),
            (f"{data_mount}/ops/{env_full}", 'ops'),
            (f"{datastorg_mount}/{project_name}/{env_name}", 'datastorg'),
        ]

        for source, sub_name in dirs_to_recycle:
            try:
                if self.directory_exists(source):
                    dest = f"{recycle_dir}/{sub_name}"
                    self.move_directory(source, dest)
                    moved.append({'source': source, 'dest': dest})
                    print(f"[回收] 已移动: {source} -> {dest}")
                else:
                    skipped.append({'path': source, 'reason': '目录不存在'})
                    print(f"[回收] 跳过: {source} (不存在)")
            except Exception as e:
                errors.append({'source': source, 'error': str(e)})
                print(f"[回收] 失败: {source} - {str(e)}")

        print(f"[回收] NFS目录回收完成: {len(moved)} 个成功, {len(skipped)} 个跳过, {len(errors)} 个失败")

        return {
            'project': env_full,
            'recycle_dir': recycle_dir,
            'moved': len(moved),
            'skipped': len(skipped),
            'failed': len(errors),
            'details': moved,
            'errors': errors
        }

    def find_latest_recycle_dir(self, project_name, env_name):
        """搜索最新的回收站目录，返回路径或 None"""
        env_full = f"{project_name}-{env_name}"
        recycle_base = '/data/recycle'
        ssh = self._get_ssh_client()
        try:
            stdin, stdout, stderr = ssh.exec_command(
                f"ls -1d {recycle_base}/{env_full}-* 2>/dev/null | sort | tail -1"
            )
            result = stdout.read().decode().strip()
            return result if result else None
        finally:
            ssh.close()

    def restore_project_dirs(self, project_name, env_name, recycle_dir):
        """
        恢复项目 NFS 目录：从回收站移动回原位

        Args:
            project_name: 项目名称
            env_name: 环境名称
            recycle_dir: 回收站目录路径（如 /data/recycle/xxx-20240101120000）

        Returns:
            dict: 恢复结果
        """
        logs_mount = _get_mount('nfs_logs_mount')
        data_mount = _get_mount('nfs_data_mount')
        datastorg_mount = _get_mount('nfs_datastorg_mount')

        env_full = f"{project_name}-{env_name}"

        restored = []
        skipped = []
        errors = []

        print(f"\n[恢复] 开始恢复NFS目录: {env_full}")
        print(f"[恢复] 回收站路径: {recycle_dir}")

        # 检查回收站目录是否存在
        if not self.directory_exists(recycle_dir):
            return {
                'project': env_full,
                'restored': 0,
                'skipped': 0,
                'failed': 1,
                'errors': [{'path': recycle_dir, 'error': '回收站目录不存在'}]
            }

        # 回收站子目录 -> 原始路径
        dirs_to_restore = [
            ('logs', f"{logs_mount}/{env_full}"),
            ('project', f"{data_mount}/{project_name}/{env_name}"),
            ('ops', f"{data_mount}/ops/{env_full}"),
            ('datastorg', f"{datastorg_mount}/{project_name}/{env_name}"),
        ]

        for sub_name, dest in dirs_to_restore:
            source = f"{recycle_dir}/{sub_name}"
            try:
                if self.directory_exists(source):
                    self.move_directory(source, dest)
                    restored.append({'source': source, 'dest': dest})
                    print(f"[恢复] 已还原: {source} -> {dest}")
                else:
                    skipped.append({'path': source, 'reason': '回收站中该目录不存在'})
                    print(f"[恢复] 跳过: {source} (不存在)")
            except Exception as e:
                errors.append({'source': source, 'dest': dest, 'error': str(e)})
                print(f"[恢复] 失败: {source} -> {dest} - {str(e)}")

        # 尝试清理空的回收站目录
        try:
            ssh = self._get_ssh_client()
            try:
                stdin, stdout, stderr = ssh.exec_command(f"rmdir {recycle_dir} 2>/dev/null")
                stdout.channel.recv_exit_status()
            finally:
                ssh.close()
        except Exception:
            pass

        print(f"[恢复] NFS目录恢复完成: {len(restored)} 个成功, {len(skipped)} 个跳过, {len(errors)} 个失败")

        return {
            'project': env_full,
            'recycle_dir': recycle_dir,
            'restored': len(restored),
            'skipped': len(skipped),
            'failed': len(errors),
            'details': restored,
            'errors': errors
        }
