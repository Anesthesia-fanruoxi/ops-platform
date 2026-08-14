# -*- coding: utf-8 -*-
"""
Kubernetes API 客户端封装（基于 admin.conf/kubeconfig 直连 API Server，不依赖 SSH kubectl）

kubeconfig 内容存于系统设置 k8s_kubeconfig；可选 k8s_api_server 覆盖 server 地址
（master 内网 IP 不可达时填 NodeIP）。
"""
import io

from modules.system.settings_service import get_setting


class KubeNotConfigured(Exception):
    """未配置 kubeconfig 或配置无效"""
    pass


def _build_core_api():
    """从系统设置构建 CoreV1Api（每次请求新建，配置修改即时生效）"""
    try:
        from kubernetes import client, config
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

    return client.CoreV1Api(client.ApiClient(client_config))


def _pod_summary(pod):
    """提取 Pod 摘要信息（状态/重启次数/节点）"""
    phase = pod.status.phase or 'Unknown'
    reason = ''
    restarts = 0
    ready = 0
    total = 0
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
    return {
        'name': pod.metadata.name,
        'phase': phase,
        'reason': reason,
        'restarts': restarts,
        'ready': f'{ready}/{total}',
        'node': pod.spec.node_name or '',
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

    用 _preload_content=False 拿原始 bytes 再 decode——
    kubernetes 36.x 默认返回 str(bytes) 的 repr（形如 b'...\\n...'，字面转义无法按行分割）。
    """
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
    """打开 Pod 日志跟随流（follow=True，SSE 实时推送用）

    Returns:
        urllib3 流式响应对象，可迭代逐行读取；使用方负责 close()
    """
    core = _build_core_api()
    kwargs = dict(name=pod_name, namespace=namespace,
                  follow=True, tail_lines=10, _preload_content=False)
    container = _pick_container(core, namespace, pod_name, prefer_container)
    if container:
        kwargs['container'] = container
    return core.read_namespaced_pod_log(**kwargs)
