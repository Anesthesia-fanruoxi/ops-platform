# -*- coding: utf-8 -*-
"""
Agent 远程安装服务：SSH 连接 → 检测系统 → 安装 Docker → 上传文件 → 启动服务
支持 Rocky 9 / Rocky 10，通过 SSE 逐步回调前端
"""
import os
import time
import uuid
import threading

import paramiko

# 安装任务内存存储（单进程足够）
_install_tasks = {}

# Agent 二进制存放目录（需预先编译好 linux 版本放入此目录）
AGENT_BINARY_DIR = os.getenv('AGENT_BINARY_DIR', os.path.join('agent', 'dist'))

# systemd service 模板
SERVICE_TEMPLATE = """[Unit]
Description=CICD Build Agent
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=root
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=/usr/local/bin/cicd-agent --name {name} --secret {secret} --master {master} --workdir {workdir} --advertise {advertise}
Restart=always
RestartSec=5
WorkingDirectory={workdir}

[Install]
WantedBy=multi-user.target
"""

# 磁盘扩容脚本（安装前置步骤）：根分区/LVM/文件系统扩展至磁盘全部剩余空间
# 镜像磁盘固定 200G、实例磁盘更大的场景，安装时自动扩到磁盘实际大小；失败以非零退出码中断安装
EXPAND_DISK_SCRIPT = r'''
#!/bin/bash
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

fail() { echo "$1"; exit 1; }

install_pkgs() {
    # 安装软件包；失败时回显实际报错（dnf 只要有一个包不存在整条就失败，可选包必须单独装）
    local out rc
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq >/dev/null 2>&1
        out=$(DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" 2>&1)
        rc=$?
    else
        out=$(dnf install -y "$@" 2>&1)
        rc=$?
        if [ "$rc" -ne 0 ] && command -v yum >/dev/null 2>&1; then
            out=$(yum install -y "$@" 2>&1)
            rc=$?
        fi
    fi
    if [ "$rc" -ne 0 ]; then
        echo "$out" | tail -n 5
    fi
    return "$rc"
}

GROWPART_PKG=cloud-utils-growpart
if command -v apt-get >/dev/null 2>&1; then GROWPART_PKG=cloud-guest-utils; fi

root_src=$(findmnt -n -o SOURCE / | head -n1)
root_fs=$(findmnt -n -o FSTYPE / | head -n1)
[ -n "$root_src" ] || fail "无法识别根挂载设备（findmnt 无输出）"
echo "根设备：$root_src（文件系统：$root_fs）"
df -h / | awk 'NR==2{print "当前容量： "$2"（已用 "$3"，可用 "$4"）"}'

is_lvm=0
if command -v lvs >/dev/null 2>&1 && lvs "$root_src" >/dev/null 2>&1; then
    is_lvm=1
fi

if [ "$is_lvm" = "1" ]; then
    # 注意：pvs 的位置参数只接受 PV 路径（传 LV 路径会查不到），先取 VG 再列该 VG 下的 PV
    vg=$(lvs --noheadings -o vg_name "$root_src" 2>/dev/null | head -n1 | tr -d ' ')
    [ -n "$vg" ] || fail "无法定位根逻辑卷 $root_src 所属的卷组"
    pv_list=$(pvs --noheadings -o vg_name,pv_name 2>/dev/null | awk -v vg="$vg" '$1 == vg {print $2}')
    [ -n "$pv_list" ] || fail "无法定位卷组 $vg 下的物理卷"
    targets="$pv_list"
    echo "布局：LVM（LV=$root_src，VG=$vg，PV=$(echo $pv_list)）"
else
    case "$root_src" in
        /dev/mapper/*) fail "根设备为 $root_src（加密/多路径映射），暂不支持自动扩容" ;;
        /dev/*) targets="$root_src"; echo "布局：直接分区（$targets）" ;;
        *) fail "无法识别的根设备：$root_src" ;;
    esac
fi

for target in $targets; do
    pkname=$(lsblk -no PKNAME "$target" 2>/dev/null | head -n1 | tr -d ' ')
    partn=$(lsblk -no PARTN "$target" 2>/dev/null | head -n1 | tr -d ' ')

    if [ -n "$pkname" ] && [ -n "$partn" ]; then
        disk="/dev/$pkname"
        disk_size=$(blockdev --getsize64 "$disk")
        part_size=$(blockdev --getsize64 "$target")
        if [ "$part_size" -ge "$disk_size" ]; then
            echo "分区 $target 已占满磁盘，无需扩容分区"
        else
            if ! command -v growpart >/dev/null 2>&1; then
                echo "缺少 growpart，正在安装 $GROWPART_PKG ..."
                install_pkgs "$GROWPART_PKG" || fail "growpart 安装失败，请检查软件源后重试"
                # gdisk（sgdisk）仅老版 util-linux 的 GPT 扩容需要；EL10 起 growpart 走 sfdisk，装不上不阻塞
                command -v sgdisk >/dev/null 2>&1 || install_pkgs gdisk || echo "提示：gdisk 不可用，GPT 分区将由 sfdisk 处理"
            fi
            grow_out=$(growpart "$disk" "$partn" 2>&1)
            grow_rc=$?
            echo "$grow_out"
            [ "$grow_rc" -eq 0 ] || fail "分区扩容失败：$grow_out"
            partx -u "$disk" >/dev/null 2>&1 || partprobe "$disk" >/dev/null 2>&1 || true
            new_part_size=$(blockdev --getsize64 "$target")
            [ "$new_part_size" -gt "$part_size" ] || fail "分区扩容未生效（内核未识别新分区大小），请重启后重试"
        fi
    elif [ -n "$pkname" ] || [ -n "$partn" ]; then
        fail "无法解析设备 $target 的磁盘/分区信息"
    else
        echo "$target 为整盘设备，跳过分区扩容"
    fi
done

if [ "$is_lvm" = "1" ]; then
    if ! command -v pvresize >/dev/null 2>&1; then
        echo "缺少 LVM 工具，正在安装 lvm2 ..."
        install_pkgs lvm2
    fi
    for target in $targets; do
        pvresize "$target" || fail "PV 扩容失败（pvresize $target）"
    done
    free_bytes=$(vgs --noheadings --units b --nosuffix -o vg_free "$vg" 2>/dev/null | tr -dc '0-9')
    echo "卷组 $vg 可扩展空间：$(( ${free_bytes:-0} / 1024 / 1024 )) MB"
    if [ "${free_bytes:-0}" -gt 0 ]; then
        lvextend -l +100%FREE "$root_src" || fail "逻辑卷扩容失败（lvextend $root_src）"
    else
        echo "卷组无可扩展空间，跳过逻辑卷扩容"
    fi
fi

case "$root_fs" in
    xfs)
        if ! command -v xfs_growfs >/dev/null 2>&1; then
            echo "缺少 xfs_growfs，正在安装 xfsprogs ..."
            install_pkgs xfsprogs
        fi
        xfs_growfs / || fail "文件系统扩容失败（xfs_growfs /）"
        ;;
    ext2|ext3|ext4)
        if ! command -v resize2fs >/dev/null 2>&1; then
            echo "缺少 resize2fs，正在安装 e2fsprogs ..."
            install_pkgs e2fsprogs
        fi
        resize2fs "$root_src" || fail "文件系统扩容失败（resize2fs $root_src）"
        ;;
    *)
        fail "文件系统 $root_fs 不支持在线扩容"
        ;;
esac

df -h / | awk 'NR==2{print "扩容后容量： "$2"（已用 "$3"，可用 "$4"）"}'
echo "磁盘扩容完成"
exit 0
'''


def create_install_task(params):
    """创建安装任务，后台线程执行，返回 task_id"""
    from flask import current_app
    task_id = uuid.uuid4().hex[:12]
    _install_tasks[task_id] = {
        'status': 'running',
        'events': [],
        'params': params,
    }
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_install, args=(task_id, app), daemon=True)
    t.start()
    return task_id


def get_install_task(task_id):
    return _install_tasks.get(task_id)


# ─── 内部执行 ──────────────────────────────────────────────────

def _emit(task_id, step, step_name, status, message=''):
    _install_tasks[task_id]['events'].append({
        'step': step,
        'step_name': step_name,
        'status': status,
        'message': message,
    })


def _run_install(task_id, app):
    """后台线程：逐步执行安装并写入事件"""
    task = _install_tasks[task_id]
    p = task['params']
    ssh = None
    try:
        # Step 1: SSH 连接 + 检测系统信息
        _emit(task_id, 1, 'SSH 连接', 'running', f"正在连接 {p['host']}:{p.get('ssh_port', 22)} ...")
        with app.app_context():
            ssh = _connect_ssh(p)
        os_info = _detect_os(ssh)
        arch = _detect_arch(ssh)
        p['_os_info'] = os_info
        p['_arch'] = arch
        _emit(task_id, 1, 'SSH 连接', 'success',
              f"连接成功 | {os_info['pretty_name']} | {arch}")

        # Step 2: 磁盘扩容（镜像磁盘固定 200G、实例磁盘更大的场景，自动扩展到磁盘实际大小）
        _emit(task_id, 2, '磁盘扩容', 'running', '正在检测磁盘剩余空间 ...')
        summary = _expand_disk(ssh, task_id)
        _emit(task_id, 2, '磁盘扩容', 'success', summary)

        # Step 3: 安装 Docker（根据系统版本执行对应命令）
        if p.get('install_docker'):
            _emit(task_id, 3, '安装 Docker', 'running',
                  f"正在检测 / 安装 Docker ({os_info['id']} {os_info['major']}) ...")
            msg = _install_docker(ssh, os_info)
            _emit(task_id, 3, '安装 Docker', 'success', msg)
        else:
            _emit(task_id, 3, '安装 Docker', 'skipped', '已跳过')

        # Step 3.5: 私有 Harbor 写入 /etc/hosts 映射
        harbor_ip = p.get('harbor_ip', '')
        harbor_url = p.get('harbor_url', '')
        if harbor_ip and harbor_url:
            _emit(task_id, 3, '安装 Docker', 'running', f'写入 hosts 映射：{harbor_ip} {harbor_url}')
            _exec(ssh, f'grep -q "{harbor_url}" /etc/hosts || echo "{harbor_ip} {harbor_url}" >> /etc/hosts')
            _emit(task_id, 3, '安装 Docker', 'success', f'hosts 映射已写入：{harbor_ip} → {harbor_url}')

        # Step 3.6: 登录 Harbor 镜像仓库
        harbor_user = p.get('harbor_user', '')
        harbor_pass = p.get('harbor_pass', '')
        if harbor_url and harbor_user and harbor_pass:
            _emit(task_id, 3, '安装 Docker', 'running', f'正在登录 Harbor：{harbor_url} ...')
            code, out, err = _exec(ssh, f'docker login {harbor_url} -u {harbor_user} -p "{harbor_pass}"')
            if code != 0:
                raise Exception(f'Harbor 登录失败: {err or out}')
            _emit(task_id, 3, '安装 Docker', 'success', f'Harbor 登录成功：{harbor_url}')

        # Step 3.7: 挂载 NFS 目录（前端发布目录，安装时自动完成，无需再登录服务器）
        nfs_server = (p.get('nfs_server') or '').strip()
        nfs_share = (p.get('nfs_share') or '').strip().rstrip('/')
        mount_dir = (p.get('frontend_mount_dir') or '').strip().rstrip('/')
        if nfs_server and nfs_share and mount_dir:
            _emit(task_id, 3, '安装 Docker', 'running',
                  f'挂载 NFS：{nfs_server}:{nfs_share} → {mount_dir} ...')
            # 1) 按系统版本安装 NFS 客户端
            os_id = (os_info.get('id') or '').lower()
            if os_id in ('ubuntu', 'debian'):
                _exec(ssh, 'apt-get update -qq && apt-get install -y nfs-common', timeout=300)
            else:
                _exec(ssh, 'dnf install -y nfs-utils || yum install -y nfs-utils', timeout=300)
            # 2) showmount 预检：确认 NFS 服务器可达且共享目录已导出
            _emit(task_id, 3, '安装 Docker', 'running',
                  f'showmount 检查：{nfs_server} ...')
            code, out, err = _exec(ssh, f'showmount -e {nfs_server} 2>&1', timeout=30)
            if code != 0:
                raise Exception(
                    f'NFS 服务器不可用：无法获取 {nfs_server} 的导出列表。'
                    f'请确认服务器已启动并 export 共享目录（{err or out}）')
            if nfs_share not in out:
                raise Exception(
                    f'NFS 共享目录 {nfs_share} 未在服务器 {nfs_server} 的导出列表中找到。'
                    f'当前导出：{out.strip()}')
            # 3) 递归创建挂载点（目录不存在会自动创建）
            _exec(ssh, f'mkdir -p {mount_dir}')
            # 4) 挂载（已挂载则跳过，避免重复/冲突）
            _exec(ssh, f'grep -q " {mount_dir} " /etc/mtab || mount -t nfs {nfs_server}:{nfs_share} {mount_dir}')
            # 5) 写 /etc/fstab 开机自动挂载（已存在则不重复写入）
            _exec(ssh, f'grep -q "{nfs_server}:{nfs_share} {mount_dir}" /etc/fstab || '
                       f'echo "{nfs_server}:{nfs_share} {mount_dir} nfs defaults 0 0" >> /etc/fstab')
            # 6) 验证挂载结果
            code, out, err = _exec(ssh, f'mountpoint -q {mount_dir} && echo OK || echo FAIL')
            if 'OK' not in out:
                raise Exception(f'NFS 挂载失败: {nfs_server}:{nfs_share} → {mount_dir} ({err or out})')
            _emit(task_id, 3, '安装 Docker', 'success',
                  f'NFS 已挂载：{nfs_server}:{nfs_share} → {mount_dir}（已写入 fstab）')

        # Step 4: 上传文件（工作目录已存在则跳过初始化、直接复用，不清理其中数据）
        _emit(task_id, 4, '上传文件', 'running', '正在上传 Agent 二进制 ...')
        workdir = p.get('work_dir', '/data/cicd')
        _, out, _ = _exec(ssh, f'[ -d {workdir} ] && echo EXISTS || echo MISSING')
        if 'EXISTS' in out:
            _emit(task_id, 4, '上传文件', 'running',
                  f'检测到工作目录已存在，跳过初始化、直接复用：{workdir}')
        else:
            _emit(task_id, 4, '上传文件', 'running',
                  f'工作目录不存在，将自动创建：{workdir}')
        _upload_files(ssh, p)
        _emit(task_id, 4, '上传文件', 'success', '二进制 / service / 配置 上传完成')

        # Step 5: 配置 systemd 并启动
        _emit(task_id, 5, '启动服务', 'running', '正在注册 systemd 并启动 ...')
        _setup_and_start(ssh, p)
        _emit(task_id, 5, '启动服务', 'success', 'cicd-agent 服务已启动')

        # 标记已安装（先提交，再发完成事件；同时清掉概览缓存）
        with app.app_context():
            from modules.cicd.models import BuildAgent
            from core.db import db
            agent = BuildAgent.query.get(p.get('agent_id'))
            if agent:
                agent.install_status = True
                db.session.commit()
            from core.redis_client import cache_delete
            cache_delete('schedule:overview')

        task['status'] = 'done'
        _emit(task_id, 0, '完成', 'done', 'Agent 安装完成，等待 Agent 注册上线 ...')

    except Exception as e:
        task['status'] = 'failed'
        _emit(task_id, 0, '失败', 'failed', str(e))
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


# ─── 系统检测 ─────────────────────────────────────────────

def _detect_os(ssh):
    """检测远程操作系统信息，返回 {id, major, pretty_name}"""
    code, out, _ = _exec(ssh, 'cat /etc/os-release')
    os_id = ''
    version_id = ''
    pretty_name = ''
    for line in out.splitlines():
        if line.startswith('ID='):
            os_id = line.split('=', 1)[1].strip('"')
        elif line.startswith('VERSION_ID='):
            version_id = line.split('=', 1)[1].strip('"')
        elif line.startswith('PRETTY_NAME='):
            pretty_name = line.split('=', 1)[1].strip('"')

    # 提取主版本号
    major = version_id.split('.')[0] if version_id else ''

    if not os_id:
        raise Exception('无法检测操作系统类型（/etc/os-release 解析失败）')

    return {
        'id': os_id,           # rocky / centos / rhel ...
        'major': major,        # 9 / 10
        'version_id': version_id,
        'pretty_name': pretty_name or f'{os_id} {version_id}',
    }


def _detect_arch(ssh):
    """检测远程机器架构"""
    code, out, _ = _exec(ssh, 'uname -m')
    if 'aarch64' in out or 'arm64' in out:
        return 'arm64'
    return 'amd64'


# ─── 磁盘扩容 ─────────────────────────────────────────────────

def _expand_disk(ssh, task_id):
    """上传并执行扩容脚本：根分区 → PV → LV → 文件系统 逐层扩展到磁盘剩余空间。
    脚本输出实时逐行推送到安装进度；失败抛异常中断安装。
    磁盘本就无剩余空间时脚本输出"无需扩容"并以 0 退出（不算失败）。
    """
    remote = '/tmp/ops-expand-disk.sh'
    sftp = ssh.open_sftp()
    try:
        _sftp_write(sftp, remote, EXPAND_DISK_SCRIPT)
    finally:
        sftp.close()

    lines = []
    try:
        stdin, stdout, stderr = ssh.exec_command(f'bash {remote} 2>&1', timeout=900)
        for line in iter(stdout.readline, ''):
            line = line.strip()
            if line:
                lines.append(line)
                _emit(task_id, 2, '磁盘扩容', 'running', line)
        code = stdout.channel.recv_exit_status()
    finally:
        try:
            _exec(ssh, f'rm -f {remote}', timeout=10)
        except Exception:
            pass

    if code != 0:
        raise Exception('磁盘扩容失败：' + (lines[-1] if lines else f'脚本退出码 {code}'))
    return lines[-1] if lines else '磁盘扩容完成'


# ─── SSH 连接 ─────────────────────────────────────────────────

def _connect_ssh(p):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    host = p['host']
    port = int(p.get('ssh_port', 22))
    username = p.get('ssh_username', 'root')
    auth_type = p.get('auth_type', 'password')

    if auth_type == 'credential':
        # 关联凭据：根据凭据类型自动选择 SSH 认证方式
        from modules.cicd.services.credential_service import decrypt_secret
        from modules.cicd.models import GitCredential
        cred = GitCredential.query.get(p.get('credential_id'))
        if not cred:
            raise Exception('凭据不存在')
        secret = decrypt_secret(cred.secret)
        if not secret:
            raise Exception('凭据密钥解密失败')

        if cred.type == 'ssh_key':
            # 私钥认证
            import io
            key_file = io.StringIO(secret)
            try:
                pkey = paramiko.RSAKey.from_private_key(key_file)
            except paramiko.ssh_exception.SSHException:
                key_file.seek(0)
                try:
                    pkey = paramiko.Ed25519Key.from_private_key(key_file)
                except Exception:
                    key_file.seek(0)
                    pkey = paramiko.ECDSAKey.from_private_key(key_file)
            ssh.connect(host, port=port, username=username, pkey=pkey, timeout=15)
        else:
            # password / token 类型：用凭据的 username+secret 作为 SSH 密码
            ssh_user = cred.username or username
            ssh.connect(host, port=port, username=ssh_user, password=secret, timeout=15)

    elif auth_type == 'ssh_key':
        # 兼容旧字段：直接传私钥内容
        from modules.cicd.services.credential_service import decrypt_secret
        from modules.cicd.models import GitCredential
        cred = GitCredential.query.get(p.get('credential_id'))
        if not cred:
            raise Exception('SSH 凭据不存在')
        key_content = decrypt_secret(cred.secret)
        if not key_content:
            raise Exception('SSH 私钥解密失败')
        import io
        key_file = io.StringIO(key_content)
        try:
            pkey = paramiko.RSAKey.from_private_key(key_file)
        except paramiko.ssh_exception.SSHException:
            key_file.seek(0)
            try:
                pkey = paramiko.Ed25519Key.from_private_key(key_file)
            except Exception:
                key_file.seek(0)
                pkey = paramiko.ECDSAKey.from_private_key(key_file)
        ssh.connect(host, port=port, username=username, pkey=pkey, timeout=15)
    else:
        # 手动密码
        password = p.get('ssh_password', '')
        if not password:
            raise Exception('SSH 密码不能为空')
        ssh.connect(host, port=port, username=username, password=password, timeout=15)

    return ssh


# ─── 文件上传 ─────────────────────────────────────────────────

def _exec(ssh, cmd, timeout=120):
    """执行远程命令，返回 (exit_code, stdout, stderr)"""
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return exit_code, out, err


def _upload_files(ssh, p):
    sftp = ssh.open_sftp()
    try:
        # 1) 上传二进制
        local_binary = os.path.join(AGENT_BINARY_DIR, 'cicd-agent')
        if not os.path.exists(local_binary):
            raise Exception(
                f'Agent 二进制不存在: {local_binary}\n'
                f'请先编译: cd agent && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 '
                f'go build -ldflags="-s -w" -o dist/cicd-agent .'
            )
        sftp.put(local_binary, '/usr/local/bin/cicd-agent')
        _exec(ssh, 'chmod +x /usr/local/bin/cicd-agent')

        # 2) 生成 systemd service（启动参数模式）
        workdir = p.get('work_dir', '/data/cicd')
        service_content = SERVICE_TEMPLATE.format(
            name=p.get('name', ''),
            secret=p.get('comm_secret', ''),
            master=p.get('master_url', '').rstrip('/'),
            workdir=workdir,
            advertise=p['host'],
        )
        _exec(ssh, f'mkdir -p {workdir}')
        _sftp_write(sftp, '/etc/systemd/system/cicd-agent.service', service_content)
    finally:
        sftp.close()


def _sftp_write(sftp, remote_path, content):
    """通过 SFTP 写入文本文件"""
    with sftp.open(remote_path, 'w') as f:
        f.write(content)


# ─── systemd 配置 + 启动 ──────────────────────────────────────

def _setup_and_start(ssh, p):
    _exec(ssh, 'systemctl daemon-reload')
    _exec(ssh, 'systemctl enable cicd-agent')
    _exec(ssh, 'systemctl restart cicd-agent')
    time.sleep(2)
    code, out, err = _exec(ssh, 'systemctl is-active cicd-agent')
    if 'active' not in out:
        _, journal, _ = _exec(ssh, 'journalctl -u cicd-agent --no-pager -n 10')
        raise Exception(f'cicd-agent 启动失败\n{journal or err}')


# ─── Docker 安装（区分 Rocky 9 / Rocky 10）─────────────────────

# Docker daemon.json 基础配置（镜像加速 + 生产参数）
DOCKER_DAEMON_BASE = {
    "registry-mirrors": [
        "https://docker.m.daocloud.io",
        "https://dockerhub.icu",
        "https://h9vtw6kz.mirror.aliyuncs.com"
    ],
    "exec-opts": ["native.cgroupdriver=systemd"],
    "log-driver": "json-file",
    "log-opts": {"max-size": "100m", "max-file": "3"},
    "storage-driver": "overlay2",
    "data-root": "/data/docker",
    "bip": "10.200.0.1/24",
    "ipv6": False,
    "live-restore": True,
    "default-ulimits": {"nofile": {"Name": "nofile", "Hard": 65535, "Soft": 65535}}
}


def _install_docker(ssh, os_info):
    """根据操作系统版本执行对应的 Docker 安装命令"""
    # 已安装则跳过包安装，但仍确保 daemon.json 配置正确
    code, out, _ = _exec(ssh, 'docker --version')
    already_installed = (code == 0 and out)

    if not already_installed:
        major = os_info['major']  # 9 / 10
        if major == '10':
            _install_docker_rocky10(ssh)
        else:
            _install_docker_rocky9(ssh)

    # 写入 daemon.json 配置（安装后 / 已安装都执行）
    _configure_docker_daemon(ssh)

    # 启动 + 验证（docker info 确认 daemon 真正运行）
    _exec(ssh, 'systemctl enable docker && systemctl restart docker')
    time.sleep(2)
    code, out, err = _exec(ssh, 'docker info --format "{{.ServerVersion}}"')
    if code != 0:
        _, journal, _ = _exec(ssh, 'journalctl -u docker --no-pager -n 10')
        raise Exception(f'Docker daemon 启动失败: {err or journal}')

    if already_installed:
        return f'Docker 已安装，daemon 运行正常: {out}'
    return f'Docker 安装成功: {out}'


def _configure_docker_daemon(ssh, insecure_registry=''):
    """创建目录 + 写入 /etc/docker/daemon.json（私有 Harbor 加入 insecure-registries）"""
    import json as _json
    cfg = dict(DOCKER_DAEMON_BASE)
    if insecure_registry:
        cfg['insecure-registries'] = [insecure_registry]
    _exec(ssh, 'mkdir -p /etc/docker /data')
    sftp = ssh.open_sftp()
    try:
        _sftp_write(sftp, '/etc/docker/daemon.json', _json.dumps(cfg, indent=2, ensure_ascii=False))
    finally:
        sftp.close()


def _install_docker_rocky9(ssh):
    """Rocky 9 Docker 安装（dnf + CentOS docker-ce 源）"""
    _exec(ssh, 'dnf install -y dnf-plugins-core', timeout=120)
    _exec(ssh,
          'dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo',
          timeout=30)
    code, out, err = _exec(ssh,
                           'dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin',
                           timeout=600)
    if code != 0:
        raise Exception(f'Docker 安装失败 (Rocky 9): {err[:500]}')


def _install_docker_rocky10(ssh):
    """Rocky 10 Docker 安装（dnf5 语法 + $releasever 替换 + nogpgcheck 回退）"""
    _exec(ssh, 'dnf install -y dnf-plugins-core', timeout=120)
    # Rocky 10 使用 dnf5，config-manager 语法不同
    code, _, _ = _exec(ssh,
                       'dnf config-manager addrepo --from-repofile=https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo',
                       timeout=30)
    if code != 0:
        # 回退: 旧版语法
        _exec(ssh,
              'dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo',
              timeout=30)

    # 将 repo 中的 $releasever 替换为 10（Rocky 10 对应 CentOS 10 源）
    _exec(ssh, "sed -i 's/$releasever/10/g' /etc/yum.repos.d/docker-ce.repo", timeout=10)

    code, out, err = _exec(ssh,
                           'dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin',
                           timeout=600)
    if code != 0:
        # 禁用 GPG 检查重试
        code, out, err = _exec(ssh,
                               'dnf install -y --nogpgcheck docker-ce docker-ce-cli containerd.io',
                               timeout=600)
        if code != 0:
            raise Exception(f'Docker 安装失败 (Rocky 10): {err[:500]}')


# ─── 远程卸载 ────────────────────────────────────────────────

def create_uninstall_task(params):
    """创建卸载任务，后台线程执行，返回 task_id"""
    from flask import current_app
    task_id = uuid.uuid4().hex[:12]
    _install_tasks[task_id] = {
        'status': 'running',
        'events': [],
        'params': params,
    }
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_uninstall, args=(task_id, app), daemon=True)
    t.start()
    return task_id


def _run_uninstall(task_id, app):
    """后台线程：逐步执行卸载并写入事件"""
    task = _install_tasks[task_id]
    p = task['params']
    ssh = None
    try:
        # Step 1: SSH 连接
        _emit(task_id, 1, 'SSH 连接', 'running', f"正在连接 {p['host']}:{p.get('ssh_port', 22)} ...")
        with app.app_context():
            ssh = _connect_ssh(p)
        _emit(task_id, 1, 'SSH 连接', 'success', '连接成功')

        # Step 2: 停止并移除 Agent 服务
        _emit(task_id, 2, '移除 Agent 服务', 'running', '正在停止并清理 cicd-agent 服务 ...')
        _exec(ssh, 'systemctl stop cicd-agent 2>/dev/null; systemctl disable cicd-agent 2>/dev/null')
        _exec(ssh, 'rm -f /etc/systemd/system/cicd-agent.service')
        _exec(ssh, 'rm -f /usr/local/bin/cicd-agent')
        _exec(ssh, 'systemctl daemon-reload')
        _emit(task_id, 2, '移除 Agent 服务', 'success', '服务已停止，二进制和 service 文件已删除')

        # Step 3: 工作目录（卸载始终删除；重置默认保留，前端可勾选删除）
        workdir = p.get('work_dir', '/data/cicd')
        if p.get('remove_workdir', True):
            _emit(task_id, 3, '删除工作目录', 'running', f'正在删除 {workdir} ...')
            # 构建产物小文件海量（.git/node_modules/target），rm 耗时可能分钟级，超时放宽到 10 分钟
            _exec(ssh, f'rm -rf {workdir}', timeout=600)
            _emit(task_id, 3, '删除工作目录', 'success', f'{workdir} 已删除')
        else:
            _emit(task_id, 3, '保留工作目录', 'skipped', f'已保留 {workdir}')

        # Step 4: 卸载 NFS 挂载（可选：重置勾选/卸载默认）
        if p.get('remove_nfs') and p.get('frontend_mount_dir'):
            mount_dir = p['frontend_mount_dir'].rstrip('/')
            _emit(task_id, 4, '卸载 NFS', 'running', f'正在卸载 {mount_dir} ...')
            _exec(ssh, f'umount -l {mount_dir} 2>/dev/null || true')
            # 从 /etc/fstab 移除对应挂载行（含 mount_dir 的行）
            _exec(ssh, f"sed -i '\\| {mount_dir} |d' /etc/fstab")
            _emit(task_id, 4, '卸载 NFS', 'success', f'{mount_dir} 已卸载，fstab 已清理')
        else:
            _emit(task_id, 4, '卸载 NFS', 'skipped', '已跳过')

        # Step 5: 卸载 Docker（可选）
        if p.get('remove_docker'):
            _emit(task_id, 5, '卸载 Docker', 'running', '正在停止并卸载 Docker ...')
            _exec(ssh, 'systemctl stop docker 2>/dev/null; systemctl disable docker 2>/dev/null')
            _exec(ssh, 'dnf remove -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin', timeout=300)
            _exec(ssh, 'rm -rf /data/docker /etc/docker')
            _emit(task_id, 5, '卸载 Docker', 'success', 'Docker 已卸载，数据目录已删除')
        else:
            _emit(task_id, 5, '卸载 Docker', 'skipped', '已跳过')

        # 删除 DB 记录（仅卸载模式，重置保留记录并标记待安装）
        with app.app_context():
            from modules.cicd.models import BuildAgent
            from core.db import db
            agent = BuildAgent.query.get(p.get('agent_id'))
            if agent:
                if p.get('delete_record'):
                    db.session.delete(agent)
                else:
                    agent.install_status = False
                    from modules.cicd.services import agent_service
                    agent_service.clear_hb(agent.id)
                db.session.commit()
            # 清掉概览缓存，保证 done 后前端立即刷新到最新状态
            from core.redis_client import cache_delete
            cache_delete('schedule:overview')

        task['status'] = 'done'
        action = '卸载' if p.get('delete_record') else '重置'
        _emit(task_id, 0, '完成', 'done', f'Agent {action}完成')

    except Exception as e:
        task['status'] = 'failed'
        _emit(task_id, 0, '失败', 'failed', str(e))
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


# ─── 远程更新（仅替换二进制 + 重启，不动 Docker/配置/工作目录）────────

def create_update_task(params):
    """创建更新任务，后台线程执行，返回 task_id"""
    from flask import current_app
    task_id = uuid.uuid4().hex[:12]
    _install_tasks[task_id] = {
        'status': 'running',
        'events': [],
        'params': params,
    }
    app = current_app._get_current_object()
    t = threading.Thread(target=_run_update, args=(task_id, app), daemon=True)
    t.start()
    return task_id


def _run_update(task_id, app):
    """后台线程：逐步执行更新并写入事件"""
    task = _install_tasks[task_id]
    p = task['params']
    ssh = None
    try:
        # Step 1: SSH 连接
        _emit(task_id, 1, 'SSH 连接', 'running', f"正在连接 {p['host']}:{p.get('ssh_port', 22)} ...")
        with app.app_context():
            ssh = _connect_ssh(p)
        _emit(task_id, 1, 'SSH 连接', 'success', '连接成功')

        # Step 2: 上传新版二进制（先传 .new 再原子 rename，避免损坏运行中的二进制）
        _emit(task_id, 2, '上传二进制', 'running', '正在上传新版 Agent 二进制 ...')
        _upload_binary_only(ssh)
        _emit(task_id, 2, '上传二进制', 'success', '二进制已上传并原子替换')

        # Step 3: 重启服务并验证
        _emit(task_id, 3, '重启服务', 'running', '正在重启 cicd-agent 服务 ...')
        _exec(ssh, 'systemctl restart cicd-agent')
        time.sleep(2)
        code, out, err = _exec(ssh, 'systemctl is-active cicd-agent')
        if 'active' not in out:
            _, journal, _ = _exec(ssh, 'journalctl -u cicd-agent --no-pager -n 10')
            raise Exception(f'cicd-agent 重启失败\n{journal or err}')
        _emit(task_id, 3, '重启服务', 'success', 'cicd-agent 已重启并运行中')

        task['status'] = 'done'
        _emit(task_id, 0, '完成', 'done', 'Agent 更新完成，等待重新上线 ...')

    except Exception as e:
        task['status'] = 'failed'
        _emit(task_id, 0, '失败', 'failed', str(e))
    finally:
        if ssh:
            try:
                ssh.close()
            except Exception:
                pass


def _upload_binary_only(ssh):
    """仅上传二进制（更新场景）：上传到 .new 后原子 rename，避免损坏运行中的二进制"""
    local_binary = os.path.join(AGENT_BINARY_DIR, 'cicd-agent')
    if not os.path.exists(local_binary):
        raise Exception(
            f'Agent 二进制不存在: {local_binary}\n'
            f'请先编译: cd agent && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 '
            f'go build -ldflags="-s -w" -o dist/cicd-agent .'
        )
    sftp = ssh.open_sftp()
    try:
        sftp.put(local_binary, '/usr/local/bin/cicd-agent.new')
        _exec(ssh, 'chmod +x /usr/local/bin/cicd-agent.new')
        _exec(ssh, 'mv -f /usr/local/bin/cicd-agent.new /usr/local/bin/cicd-agent')
    finally:
        sftp.close()
