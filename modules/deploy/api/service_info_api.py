# -*- coding: utf-8 -*-
"""
服务信息接口：选环境查看各服务

- 服务列表（deployment YAML + k8s Pod 状态）
- Pod 运行日志（SSE 实时流：先回放历史，再 follow 跟随）
- 服务部署 YAML 原文
- Nacos 配置查看/修改（Nacos Open API）
"""
import json
import os

import yaml
from flask import request, Response

from core.response import success_response, error_response
from core.security import require_permission
from modules.deploy.api.shared import get_output_dir


# ─── 公共工具 ─────────────────────────────────────────────

def _env_base_path(project, env):
    """环境生成目录；不存在返回 ('', 错误响应)"""
    base = os.path.join(get_output_dir(), f'{project}-{env}')
    if not os.path.exists(base):
        return '', error_response(f'环境 {project}-{env} 不存在（无生成目录）', 404)
    return base, None


def _parse_deployments(base_path):
    """解析 deployment 目录 → [{name, image, replicas, ports, namespace, file, envs}]
    ports 取 service 映射端口（nodePort，无则 port）；envs 取主容器环境变量（name/value）
    """
    result = []
    deploy_dir = os.path.join(base_path, 'deployment')
    if not os.path.exists(deploy_dir):
        return result
    for f in sorted(os.listdir(deploy_dir)):
        if not (f.endswith('.yaml') or f.endswith('.yml')):
            continue
        try:
            with open(os.path.join(deploy_dir, f), 'r', encoding='utf-8') as fp:
                doc = yaml.safe_load(fp)
            if not doc or doc.get('kind') != 'Deployment':
                continue
            spec = doc.get('spec', {})
            containers = spec.get('template', {}).get('spec', {}).get('containers', [])
            main = None
            envs = []
            for c in containers:
                if c.get('name') == 'filebeat':
                    continue
                if main is None:
                    main = c
                for e in (c.get('env') or []):
                    ename = e.get('name', '')
                    if not ename:
                        continue
                    if 'value' in e:
                        envs.append({'name': ename, 'value': str(e['value'])})
                    elif 'valueFrom' in e:
                        src = 'valueFrom'
                        vf = e['valueFrom'] or {}
                        if 'fieldRef' in vf:
                            src = 'fieldRef:' + (vf['fieldRef'].get('fieldPath', '') or '')
                        elif 'configMapKeyRef' in vf:
                            src = 'configMap:' + (vf['configMapKeyRef'].get('name', '') or '')
                        elif 'secretKeyRef' in vf:
                            src = 'secret:' + (vf['secretKeyRef'].get('name', '') or '')
                        envs.append({'name': ename, 'value': '', 'source': src})
            # 端口：优先 service 映射端口（nodePort），无则 deployment containerPort
            ports = _load_service_ports(base_path, doc.get('metadata', {}).get('name', f.replace('.yaml', '')))
            if not ports:
                for c in containers:
                    if c.get('name') == 'filebeat':
                        continue
                    for p in (c.get('ports') or []):
                        if p.get('containerPort'):
                            ports.append({'label': '端口', 'port': str(p['containerPort'])})
            result.append({
                'name': doc.get('metadata', {}).get('name', f.replace('.yaml', '')),
                'image': (main or {}).get('image', ''),
                'replicas': spec.get('replicas', 1),
                'ports': ports,
                'namespace': doc.get('metadata', {}).get('namespace', ''),
                'file': f,
                'envs': envs,
            })
        except Exception:
            continue
    return result


def _load_service_ports(base_path, service_name):
    """从 service 目录读端口：优先 nodePort（外部映射），无则 port；
    排除 jmx 监控端口，仅保留 debug / 业务端口；
    返回 [{label, port}]，label 为端口用途（debug/服务/端口）"""
    ports = []
    service_dir = os.path.join(base_path, 'service')
    for suffix in ('', '.yaml', '.yml'):
        path = os.path.join(service_dir, service_name + suffix)
        if os.path.exists(path):
            break
    else:
        return ports
    try:
        with open(path, 'r', encoding='utf-8') as fp:
            doc = yaml.safe_load(fp)
        for p in (doc.get('spec', {}).get('ports') or []):
            name = (p.get('name') or '').lower()
            if name == 'jmx':
                continue
            node_port = p.get('nodePort')
            port = p.get('port')
            label = {'debug': 'debug', 'service': '服务'}.get(name, name or '端口')
            if node_port:
                ports.append({'label': label, 'port': str(node_port)})
            elif port:
                ports.append({'label': label, 'port': str(port)})
    except Exception:
        pass
    return ports


# ─── 服务列表 ─────────────────────────────────────────────

@require_permission('page:service_info')
def list_services():
    """环境服务列表：deployment 基本信息 + k8s Pod 运行状态"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    if not project or not env:
        return error_response('缺少参数 project / env', 400)

    base, err = _env_base_path(project, env)
    if err:
        return err

    services = _parse_deployments(base)
    k8s_error = ''
    try:
        from modules.deploy.services.kube_client import list_pods
        for svc in services:
            ns = svc['namespace'] or f'{project}-{env}-service'
            try:
                svc['pods'] = list_pods(ns, f"app={svc['name']}")
            except Exception as e:
                svc['pods'] = []
                if not k8s_error:
                    k8s_error = str(e)
    except Exception as e:
        # kubernetes 依赖/kubeconfig 未配置：列表仍返回，Pod 状态留空
        k8s_error = str(e)
        for svc in services:
            svc['pods'] = []

    return success_response({'list': services, 'k8s_error': k8s_error})


# ─── Pod 日志 SSE 流 ──────────────────────────────────────

@require_permission('page:service_info')
def pod_log_stream():
    """Pod 日志 SSE 流：先回放最近 N 行历史，再 follow 实时跟随。

    EventSource 无法带 Header，token 走 query 参数（core/security 已支持）。
    """
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    pod = request.args.get('pod', '')
    service = request.args.get('service', '')
    tail = request.args.get('tail', '500', type=int)
    if not project or not env or not pod:
        return error_response('缺少参数 project / env / pod', 400)
    tail = max(50, min(tail, 5000))
    namespace = f'{project}-{env}-service'

    from modules.deploy.services.kube_client import read_pod_log, stream_pod_log

    # 生成器懒执行（响应返回后请求上下文已 pop），先捕获 app 对象，
    # 在生成器内手动推入应用上下文，否则 get_setting 访问 DB 报
    # Working outside of application context
    from flask import current_app
    app_obj = current_app._get_current_object()

    def generate():
        stream = None
        with app_obj.app_context():
            try:
                # 历史回放
                history = read_pod_log(namespace, pod, tail_lines=tail, prefer_container=service)
                for line in history.splitlines():
                    yield f'data: {json.dumps({"line": line}, ensure_ascii=False)}\n\n'
                # 实时跟随（逐行迭代；Pod 结束/连接断开时流自然结束）
                stream = stream_pod_log(namespace, pod, prefer_container=service)
                for raw in stream:
                    line = raw.decode('utf-8', errors='replace').rstrip('\n')
                    yield f'data: {json.dumps({"line": line}, ensure_ascii=False)}\n\n'
                yield f'data: {json.dumps({"end": True}, ensure_ascii=False)}\n\n'
            except GeneratorExit:
                return
            except Exception as e:
                try:
                    yield f'data: {json.dumps({"error": str(e)}, ensure_ascii=False)}\n\n'
                except Exception:
                    pass
            finally:
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ─── 服务部署 YAML ────────────────────────────────────────

@require_permission('page:service_info')
def service_yaml():
    """返回服务 deployment YAML 原文"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    service = request.args.get('service', '')
    if not project or not env or not service:
        return error_response('缺少参数 project / env / service', 400)

    base, err = _env_base_path(project, env)
    if err:
        return err

    deploy_dir = os.path.join(base, 'deployment')
    for f in (f'{service}.yaml', f'{service}.yml'):
        path = os.path.join(deploy_dir, f)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as fp:
                return success_response({'file': f, 'content': fp.read()})
    return error_response(f'未找到服务 {service} 的 deployment YAML', 404)


# ─── Nacos 配置 ───────────────────────────────────────────

def _build_nacos_http(project, env, global_config=False):
    """解析环境 Nacos 地址与 tenant，构建客户端；失败返回 (None, None, 错误响应)
    global_config=True 时 tenant 置空（public namespace，读取全局 application.yaml）
    """
    from modules.deploy.services.nacos_http_client import resolve_nacos_endpoint, NacosHttpClient
    try:
        base_url, tenant = resolve_nacos_endpoint(project, env)
    except ValueError as e:
        return None, None, error_response(str(e), 400)
    if global_config:
        tenant = ''
    return NacosHttpClient(base_url), tenant, None


@require_permission('page:service_info')
def nacos_config_detail():
    """单个配置内容"""
    project = request.args.get('project', '')
    env = request.args.get('env', '')
    data_id = request.args.get('dataId', '')
    group = request.args.get('group', 'DEFAULT_GROUP')
    global_config = request.args.get('global', '') == '1'
    if not project or not env or not data_id:
        return error_response('缺少参数 project / env / dataId', 400)

    client, tenant, err = _build_nacos_http(project, env, global_config)
    if err:
        return err
    try:
        content = client.get_config(tenant, data_id, group)
    except ValueError as e:
        msg = str(e)
        # Nacos 对不存在的配置返回 404 config data not exist，透传 404 供前端引导新增
        if '（404）' in msg or 'config data not exist' in msg.lower():
            return error_response(f'配置 {data_id} 不存在', 404)
        return error_response(msg, 500)
    except Exception as e:
        return error_response(str(e), 500)
    return success_response({'dataId': data_id, 'group': group, 'content': content})


@require_permission('op:nacos_config_update')
def nacos_config_publish():
    """发布/更新配置"""
    data = request.json or {}
    project = data.get('project', '')
    env = data.get('env', '')
    data_id = data.get('dataId', '')
    group = data.get('group', 'DEFAULT_GROUP')
    content = data.get('content', '')
    global_config = bool(data.get('global'))
    if not project or not env or not data_id:
        return error_response('缺少参数 project / env / dataId', 400)

    client, tenant, err = _build_nacos_http(project, env, global_config)
    if err:
        return err
    try:
        client.publish_config(tenant, data_id, group, content)
    except Exception as e:
        return error_response(str(e), 500)
    return success_response({'dataId': data_id, 'group': group})
