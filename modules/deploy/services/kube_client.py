# -*- coding: utf-8 -*-
"""
Kubernetes API 客户端封装（基于 admin.conf/kubeconfig 直连 API Server，不依赖 SSH kubectl）

kubeconfig 内容存于系统设置 k8s_kubeconfig；可选 k8s_api_server 覆盖 server 地址
（master 内网 IP 不可达时填 NodeIP）。
"""

from modules.system.settings_service import get_setting


class KubeNotConfigured(Exception):
    """未配置 kubeconfig 或配置无效"""
    pass


def _build_client_config():
    """从系统设置构建客户端配置（每次请求新建，配置修改即时生效）"""
    try:
        from kubernetes import client
    except ImportError:
        raise KubeNotConfigured('未安装 kubernetes 依赖，请执行 pip install kubernetes')

    kubeconfig_text = get_setting('k8s_kubeconfig', '')
    if not kubeconfig_text:
        raise KubeNotConfigured('系统设置未配置 k8s_kubeconfig（K8s admin.conf），请在系统设置页粘贴保存')

    try:
        # KubeConfigLoader 在 kubernetes 36.x 位于 kubernetes.config.kube_config；
        # 传 config_dict（dict）而非文件路径/StringIO
        from kubernetes.config.kube_config import KubeConfigLoader
        import yaml
        loader = KubeConfigLoader(config_dict=yaml.safe_load(kubeconfig_text))
        client_config = client.Configuration()
        loader.load_and_set(client_config)
    except Exception as e:
        raise KubeNotConfigured(f'kubeconfig 解析失败: {e}')

    api_server = get_setting('k8s_api_server', '')
    if api_server:
        client_config.host = api_server
    client_config.assert_hostname = False
    return client_config


def _build_core_api():
    """构建 CoreV1Api（Pod/Service/日志）"""
    from kubernetes import client
    return client.CoreV1Api(client.ApiClient(_build_client_config()))


def _build_apps_api():
    """构建 AppsV1Api（Deployment 不在 CoreV1Api 上）"""
    from kubernetes import client
    return client.AppsV1Api(client.ApiClient(_build_client_config()))


def _pod_summary(pod):
    """提取 Pod 摘要信息（状态/重启次数/节点/实际运行镜像/app 标签）"""
    phase = pod.status.phase or 'Unknown'
    reason = ''
    restarts = 0
    ready = 0
    total = 0
    image = ''
    for cs in (pod.status.container_statuses or []):
        restarts += cs.restart_count or 0
        total += 1
        if cs.ready:
            ready += 1
        state = cs.state
        if state.waiting and state.waiting.reason:
            reason = state.waiting.reason
        elif state.terminated and state.terminated.reason:
            reason = state.terminated.reason
        # 实际运行镜像取主容器（跳过 filebeat）
        if not image and cs.name != 'filebeat' and cs.image:
            image = cs.image
    labels = pod.metadata.labels or {}
    return {
        'name': pod.metadata.name,
        'phase': phase,
        'reason': reason,
        'restarts': restarts,
        'ready': f'{ready}/{total}',
        'node': pod.spec.node_name or '',
        'image': image,
        'app': labels.get('app', ''),
    }


def _pick_container(core, namespace, pod_name, prefer=''):
    """多容器 Pod 读日志必须指定 container。

    优先级：与服务同名容器 > 第一个非 filebeat 容器 > 第一个容器；
    单容器 Pod 返回 None（无需指定）。
    """
    try:
        pod = core.read_namespaced_pod(name=pod_name, namespace=namespace)
    except Exception:
        return prefer or None
    names = [c.name for c in (pod.spec.containers or [])]
    if len(names) <= 1:
        return None
    if prefer and prefer in names:
        return prefer
    for n in names:
        if n != 'filebeat':
            return n
    return names[0]


def list_deployments(namespace):
    """实时读取 namespace 下所有 Deployment（镜像/副本/容器 env），返回 [{name, image, replicas, containers}]"""
    api = _build_apps_api()
    try:
        deps = api.list_namespaced_deployment(namespace=namespace)
    except Exception as e:
        raise KubeNotConfigured(f'读取 Deployment 失败: {e}')
    result = []
    for d in deps.items:
        spec = d.spec or None
        pod_spec = getattr(spec, 'template', None) and spec.template.spec or None
        containers = []
        main = None
        if pod_spec:
            containers = [
                {
                    'name': c.name,
                    'image': c.image or '',
                    'env': [
                        {
                            'name': e.name,
                            'value': e.value if e.value is not None else '',
                            'value_from': e.value_from is not None,
                            'source': _env_source(e.value_from),
                        } for e in (c.env or [])
                    ],
                    'container_ports': [
                        {
                            'name': cp.name or '',
                            'port': cp.container_port if cp.container_port else '',
                        } for cp in (c.ports or [])
                    ],
                } for c in pod_spec.containers
            ]
            for c in containers:
                if c['name'] != 'filebeat':
                    main = c
                    break
            if main is None and containers:
                main = containers[0]
        result.append({
            'name': d.metadata.name,
            'image': (main or {}).get('image', ''),
            'replicas': getattr(spec, 'replicas', None) or 1,
            'containers': containers,
            'envs': (main or {}).get('env', []) if main else [],
        })
    return result


def _env_source(value_from):
    """解析 env.valueFrom 来源标签（fieldRef/configMap/secret）"""
    if not value_from:
        return ''
    if value_from.field_ref:
        return 'fieldRef:' + (value_from.field_ref.field_path or '')
    if value_from.config_map_key_ref:
        return 'configMap:' + (value_from.config_map_key_ref.name or '')
    if value_from.secret_key_ref:
        return 'secret:' + (value_from.secret_key_ref.name or '')
    return 'valueFrom'


def list_k8s_services(namespace):
    """实时读取 namespace 下所有 Service（nodePort/port 映射）"""
    api = _build_core_api()
    try:
        svcs = api.list_namespaced_service(namespace=namespace)
    except Exception as e:
        raise KubeNotConfigured(f'读取 Service 失败: {e}')
    result = []
    for svc in svcs.items:
        ports = []
        for p in (svc.spec.ports or []):
            ports.append({
                'name': p.name or '',
                'port': str(p.port or ''),
                'node_port': str(p.node_port or '') if p.node_port else '',
                'target_port': str(p.target_port or '') if p.target_port else '',
            })
        result.append({'name': svc.metadata.name, 'ports': ports})
    return result


def list_pods(namespace, label_selector=''):
    """列出命名空间下 Pod（可按 label 过滤）"""
    core = _build_core_api()
    kwargs = {}
    if label_selector:
        kwargs['label_selector'] = label_selector
    pods = core.list_namespaced_pod(namespace, **kwargs)
    return [_pod_summary(p) for p in pods.items]


def read_pod_log(namespace, pod_name, tail_lines=500, prefer_container=''):
    """读取 Pod 历史日志（快照，SSE 回放用）；多容器自动选主容器。
    _preload_content=False 拿原始 bytes 再 decode（kubernetes 36.x 默认返回字面转义的 repr）"""
    core = _build_core_api()
    kwargs = dict(name=pod_name, namespace=namespace,
                  tail_lines=tail_lines, timestamps=False, _preload_content=False)
    container = _pick_container(core, namespace, pod_name, prefer_container)
    if container:
        kwargs['container'] = container
    resp = core.read_namespaced_pod_log(**kwargs)
    data = resp.data if hasattr(resp, 'data') else resp
    if isinstance(data, bytes):
        return data.decode('utf-8', errors='replace')
    return str(data) or ''


def stream_pod_log(namespace, pod_name, prefer_container=''):
    """打开 Pod 日志跟随流（follow=True，SSE 实时推送用）；返回流式响应对象，使用方负责 close()"""
    core = _build_core_api()
    kwargs = dict(name=pod_name, namespace=namespace,
                  follow=True, tail_lines=10, _preload_content=False)
    container = _pick_container(core, namespace, pod_name, prefer_container)
    if container:
        kwargs['container'] = container
    return core.read_namespaced_pod_log(**kwargs)


def _watch(api, list_fn, namespace, timeout_seconds, mapper):
    """Watch 命名空间资源事件流；timeout_seconds 到期自然结束，调用方循环重建"""
    from kubernetes import watch
    w = watch.Watch()
    for event in w.stream(list_fn, namespace=namespace, timeout_seconds=timeout_seconds):
        yield event['type'], mapper(event['object'])


def watch_deployments(namespace, timeout_seconds=30):
    """Watch Deployment 事件，产出 (event_type, deployment_name)；副本/策略变更触发重建快照"""
    return _watch(_build_apps_api(), _build_apps_api().list_namespaced_deployment,
                  namespace, timeout_seconds, lambda o: o.metadata.name)


def watch_pods(namespace, timeout_seconds=30):
    """Watch Pod 事件，产出 (event_type, pod_summary)；滚动更新期间实时反映 Pod 状态/镜像变化"""
    return _watch(_build_core_api(), _build_core_api().list_namespaced_pod,
                  namespace, timeout_seconds, _pod_summary)


def build_service_snapshot(namespace):
    """构建服务卡片快照（Deployment × Service 端口 × Pod 状态/实际镜像）

    镜像取 Pod 实际运行镜像（container_statuses[].image，按出现顺序去重；
    无 Pod 时回退 Deployment spec 镜像）；Pod 按 app 标签归属服务。
    K8s 异常统一抛 KubeNotConfigured，由调用方回退。
    """
    deps = list_deployments(namespace)
    k8s_svcs = {s['name']: s['ports'] for s in list_k8s_services(namespace)}
    pods_map = {}
    for pod in list_pods(namespace):
        key = pod.get('app') or ''
        if key:
            pods_map.setdefault(key, []).append(pod)

    services = []
    for d in deps:
        name = d['name']
        ports = []
        for p in k8s_svcs.get(name) or []:
            if p.get('node_port'):
                ports.append({'label': p.get('name') or '端口', 'port': p['node_port']})
        if not ports:
            for c in d['containers']:
                if c['name'] == 'filebeat':
                    continue
                for p in c.get('container_ports') or []:
                    if p.get('port'):
                        ports.append({'label': p.get('name') or '端口', 'port': str(p['port'])})
        pods = pods_map.get(name) or []
        pod_images = []
        for p in pods:
            img = p.get('image') or ''
            if img and img not in pod_images:
                pod_images.append(img)
        services.append({
            'name': name,
            'image': pod_images[0] if pod_images else d['image'],
            'images': pod_images,  # 去重后的实际运行镜像集合（滚动更新期间多镜像并存）
            'replicas': d['replicas'],
            'ports': ports,
            'namespace': namespace,
            'pods': pods,
            # 设计决策：envs 不随列表/SSE 携带，弹窗时走 /service-info/envs 实时读 K8s
        })
    return services
