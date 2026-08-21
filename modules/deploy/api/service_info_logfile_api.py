# -*- coding: utf-8 -*-
"""
服务信息-日志目录接口（SSH 直连 NFS 服务器）

- GET /service-info/logfiles          列出服务日志目录文件
- GET /service-info/logfile/content   读取日志文件全文（≤10MB）
- GET /service-info/logfile/download  流式下载日志文件
"""
import os
from datetime import datetime

from flask import request, Response

from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.services.nfs_service import NFSService
from modules.system.settings_service import get_setting

# 全文读取上限；超出改为读末尾 TAIL_BYTES（大文件全量渲染前端会卡）
FULL_LIMIT = 20 * 1024 * 1024
TAIL_BYTES = 2 * 1024 * 1024


def _log_dir(project, env, service):
    """服务日志目录：{nfs_logs_mount}/{project}-{env}/{project}-{短名}
    service 传入的是 K8s Deployment 全名（已含项目前缀，如 bjjf-app），
    而 NFS 目录由服务配置短名创建（{project}-{name}），不能重复拼项目名"""
    logs_mount = (get_setting('nfs_logs_mount', '') or '').rstrip('/')
    if not logs_mount:
        return '', '未配置 nfs_logs_mount（NFS 日志挂载路径）'
    prefix = f'{project}-'
    short_name = service[len(prefix):] if service.startswith(prefix) else service
    return f'{logs_mount}/{project}-{env}/{project}-{short_name}', ''


def _safe_filename(name):
    """文件名校验：禁止路径分隔符与上级目录，防路径穿越"""
    if not name or '/' in name or '\\' in name or '..' in name or name != os.path.basename(name):
        return False
    return True


def _format_size(size):
    """字节数 → 可读字符串"""
    units = ['B', 'KB', 'MB', 'GB']
    idx = 0
    val = float(size)
    while val >= 1024 and idx < len(units) - 1:
        val /= 1024
        idx += 1
    return f'{val:.1f}{units[idx]}' if idx else f'{int(val)}B'


@require_permission('page:service_info')
def logfile_list():
    """列出服务日志目录下的文件（按修改时间倒序）"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    service = request.args.get('service', '')
    if not project or not env or not service:
        return error_response('缺少参数 project / env / service', 400)

    log_dir, err = _log_dir(project, env, service)
    if err:
        return error_response(err, 500)

    try:
        nfs = NFSService()
        if not nfs.directory_exists(log_dir):
            return success_response({'path': log_dir, 'list': [], 'message': '日志目录不存在'})
        files = nfs.list_files(log_dir)
    except Exception as e:
        return error_response(f'读取日志目录失败: {e}', 500)

    for f in files:
        f['size_str'] = _format_size(f['size'])
        f['mtime_str'] = datetime.fromtimestamp(f['mtime']).strftime('%Y-%m-%d %H:%M:%S') if f['mtime'] else ''
    files.sort(key=lambda x: x['mtime'], reverse=True)
    return success_response({'path': log_dir, 'list': files})


@require_permission('page:service_info')
def logfile_content():
    """读取日志文件全文；超过上限拒绝并提示下载"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    service = request.args.get('service', '')
    filename = request.args.get('file', '')
    if not project or not env or not service or not filename:
        return error_response('缺少参数 project / env / service / file', 400)
    if not _safe_filename(filename):
        return error_response('非法文件名', 400)

    log_dir, err = _log_dir(project, env, service)
    if err:
        return error_response(err, 500)

    ssh, sftp = None, None
    try:
        nfs = NFSService()
        ssh, sftp = nfs.open_sftp(log_dir)
        remote_file = f'{log_dir}/{filename}'
        size = sftp.stat(remote_file).st_size or 0
        truncated = False
        with sftp.open(remote_file, 'rb') as fp:
            if size <= FULL_LIMIT:
                raw = fp.read()
            else:
                # 大文件只读末尾，丢弃首行残行
                fp.seek(max(size - TAIL_BYTES, 0))
                raw = fp.read()
                nl = raw.find(b'\n')
                if 0 <= nl < len(raw) - 1:
                    raw = raw[nl + 1:]
                truncated = True
        content = raw.decode('utf-8', errors='replace')
        return success_response({'file': filename, 'size': size, 'content': content, 'truncated': truncated})
    except Exception as e:
        return error_response(f'读取文件失败: {e}', 500)
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        if ssh is not None:
            try:
                ssh.close()
            except Exception:
                pass


@require_permission('page:service_info')
def logfile_download():
    """流式下载日志文件（token 走 query，同 SSE 日志流）"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    service = request.args.get('service', '')
    filename = request.args.get('file', '')
    if not project or not env or not service or not filename:
        return error_response('缺少参数 project / env / service / file', 400)
    if not _safe_filename(filename):
        return error_response('非法文件名', 400)

    log_dir, err = _log_dir(project, env, service)
    if err:
        return error_response(err, 500)

    try:
        nfs = NFSService()
        ssh, sftp = nfs.open_sftp(log_dir)
    except Exception as e:
        return error_response(f'打开日志目录失败: {e}', 500)

    remote_file = f'{log_dir}/{filename}'
    try:
        fp = sftp.open(remote_file, 'rb')
    except Exception as e:
        sftp.close()
        ssh.close()
        return error_response(f'文件不存在或读取失败: {e}', 404)

    def generate():
        try:
            while True:
                chunk = fp.read(65536)
                if not chunk:
                    break
                yield chunk
        except GeneratorExit:
            pass
        finally:
            try:
                fp.close()
            except Exception:
                pass
            try:
                sftp.close()
            except Exception:
                pass
            try:
                ssh.close()
            except Exception:
                pass

    return Response(
        generate(),
        mimetype='application/octet-stream',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )
