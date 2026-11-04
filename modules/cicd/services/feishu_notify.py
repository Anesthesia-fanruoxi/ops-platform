# -*- coding: utf-8 -*-
"""
发版完成飞书卡片通知

流程模板的最后一个步骤（key='notify'）：构建/部署结束后，把发版结果推送到飞书群机器人。

- 开关与 Webhook 地址来自流程模板 configs[backend|frontend]（notify_enabled / notify_webhook_url /
  notify_webhook_secret）；地址留空时回退到系统设置 feishu_webhook_url / feishu_webhook_secret
- 通知步骤由 Master 执行（Agent 不感知）：成功/失败/跳过都会更新步骤状态，便于构建面板展示
- best-effort：Webhook 发送失败只记日志并把通知步骤标为 failed，不影响构建/部署终态
"""
import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime

import requests
from flask import current_app

logger = logging.getLogger(__name__)

# Webhook 请求超时（秒）
WEBHOOK_TIMEOUT = 8


def _truthy(value):
    """兼容 bool / '1' / 'true' / 'on' 等模板 JSON 存储形式"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _template_notify_cfg(build):
    """读取流程模板中当前项目类型的通知配置；模板缺失返回空 dict"""
    from modules.cicd.models import CicdFlowTemplate
    tpl = CicdFlowTemplate.query.filter_by(project_id=build.project_id).first()
    if not tpl:
        return {}
    cfg = tpl.configs_dict().get(build.project_type or 'backend') or {}
    return cfg if isinstance(cfg, dict) else {}


def _resolve_webhook(build):
    """解析 Webhook 地址与签名密钥（三级兜底）：

    1. 流程模板填了地址 → 用模板的地址 + 模板的密钥（密钥按该机器人填写）；
    2. 模板只开启未填地址 → 整体回退系统设置（地址与密钥成对取，避免拿错机器人的密钥）；
    3. 两处都没有 → 返回空地址，调用方跳过通知。

    返回 (url, secret, enabled)；enabled=False 表示流程模板未开启通知。
    """
    cfg = _template_notify_cfg(build)
    enabled = _truthy(cfg.get('notify_enabled'))
    url = (cfg.get('notify_webhook_url') or '').strip()
    secret = (cfg.get('notify_webhook_secret') or '').strip()
    if not url:
        from modules.system.settings_service import get_setting
        url = (get_setting('feishu_webhook_url', '') or '').strip()
        # 地址来自系统设置时，密钥也取系统设置的（签名密钥与机器人一一对应）
        secret = (get_setting('feishu_webhook_secret', '') or '').strip()
    return url, secret, enabled


def _gen_sign(secret, timestamp):
    """飞书自定义机器人签名：HMAC-SHA256(key=f'{timestamp}\\n{secret}', msg='') → base64"""
    string_to_sign = f'{timestamp}\n{secret}'
    hmac_code = hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
    return base64.b64encode(hmac_code).decode('utf-8')


def _field(label, value, short=True):
    """卡片双列字段"""
    text = str(value if value not in (None, '') else '-')
    return {'is_short': short, 'text': {'tag': 'lark_md', 'content': f'**{label}**\n{text}'}}


def _fmt_duration(seconds):
    """秒 → 构建用时文案（对齐截图风格：3 min 3 sec）"""
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        return '-'
    if total <= 0:
        return '-'
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours} h {minutes} min' if minutes else f'{hours} h'
    if minutes:
        return f'{minutes} min {secs} sec'
    return f'{secs} sec'


def _project_display_name(build):
    """项目展示名：优先中文名（projects.description，如 ysh → 云盛花）。

    自动导入项目的 description 为「自动导入: xxx」或无意义长文本，这类回退用 name。
    """
    proj = build.project
    if not proj:
        return '-'
    name = (proj.name or '').strip()
    desc = (getattr(proj, 'description', '') or '').strip()
    if desc and not desc.startswith('自动导入') and len(desc) <= 20:
        return desc
    return name or '-'


def build_card(build, deploy_status=None, deploy_error=''):
    """组装飞书消息卡片（emoji 逐行样式）：标题=项目中文名 » 项目名-环境名 + 状态，绿=成功、红=失败；
    正文逐行展示任务名称 / 构建编号 / 分支 / 构建状态 / 构建用时 / 执行者 / 镜像版本，
    分隔线下为发版时间与固定署名。
    """
    project_name = _project_display_name(build)
    env_name = (build.environment.name if build.environment else '') or '-'
    # 标题后半段固定为 projects.name-environments.name（如 ysh-dev），与部署目录/镜像命名一致
    proj_code = (build.project.name if build.project else '') or env_name
    env_full = f'{proj_code}-{env_name}' if proj_code else env_name
    # 构建失败或部署失败都算发版失败（红色），其余为成功（绿色）
    ok = build.status == 'success' and deploy_status != 'failed'
    status_text = '成功' if ok else '失败'
    title = f'📢 {project_name} » {env_full} {status_text}'
    finished = build.finished_at or datetime.now()

    lines = [
        f'📋 任务名称：{project_name} » {env_full}',
        f'🔢 构建编号：{build.build_no or "-"}',
        f'🌿 分　　支：{build.branch or "-"}',
        f'🌟 构建状态：{status_text}',
        f'🕐 构建用时：{_fmt_duration(build.duration)}',
        f'👤 执 行 者：{build.triggered_by or "-"}',
        f'🏷 镜像版本：{build.image_tag or "-"}',
    ]

    elements = [
        {'tag': 'div', 'text': {'tag': 'lark_md', 'content': '\n'.join(lines)}},
        {'tag': 'hr'},
        {'tag': 'div', 'text': {'tag': 'lark_md',
                                'content': f'**发版时间**：{finished.strftime("%Y-%m-%d %H:%M:%S")}'}},
        {'tag': 'hr'},
        {'tag': 'note', 'elements': [{'tag': 'plain_text', 'content': '运维平台 · 自动发版通知'}]},
    ]

    return {
        'msg_type': 'interactive',
        'card': {
            'config': {'wide_screen_mode': True},
            'header': {
                'template': 'green' if ok else 'red',
                'title': {'tag': 'plain_text', 'content': title},
            },
            'elements': elements,
        },
    }


def send_card(url, secret, card):
    """POST 卡片到飞书自定义机器人；返回 (ok, message)"""
    payload = dict(card)
    if secret:
        ts = str(int(time.time()))
        payload['timestamp'] = ts
        payload['sign'] = _gen_sign(secret, ts)
    try:
        resp = requests.post(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Content-Type': 'application/json; charset=utf-8'},
            timeout=WEBHOOK_TIMEOUT,
        )
    except requests.RequestException as e:
        return False, f'请求失败: {e}'

    try:
        body = resp.json()
    except ValueError:
        return False, f'HTTP {resp.status_code}: {resp.text[:200]}'
    # 飞书新版本返回 code/msg，旧版本返回 StatusCode/StatusMessage
    code = body.get('code', body.get('StatusCode'))
    if resp.status_code == 200 and code in (0, None):
        return True, '发送成功'
    msg = body.get('msg') or body.get('StatusMessage') or resp.text[:200]
    return False, f'code={code}, msg={msg}'


def notify_release(build, deploy_status=None, deploy_error=''):
    """执行「发版通知」步骤：读配置 → 发卡片 → 回写步骤状态。
    返回 (ok, message)；未开启/未配置时也返回 False 并说明原因（步骤标 skipped）。
    """
    from modules.cicd.services.build_service import update_step_by_key

    build_no = build.build_no
    url, secret, enabled = _resolve_webhook(build)

    if not enabled:
        update_step_by_key(build_no, 'notify', 'skipped', '流程模板未开启发版通知')
        return False, '流程模板未开启发版通知'
    if not url:
        msg = '未配置飞书 Webhook（流程模板与系统设置均为空）'
        update_step_by_key(build_no, 'notify', 'skipped', msg)
        return False, msg
    if not url.startswith(('http://', 'https://')):
        update_step_by_key(build_no, 'notify', 'failed', f'Webhook 地址不合法: {url}')
        return False, 'Webhook 地址不合法'

    update_step_by_key(build_no, 'notify', 'running')
    card = build_card(build, deploy_status=deploy_status, deploy_error=deploy_error)
    ok, msg = send_card(url, secret, card)
    if ok:
        update_step_by_key(build_no, 'notify', 'success')
        logger.info('[Notify] 构建#%s 发版通知发送成功', build_no)
    else:
        update_step_by_key(build_no, 'notify', 'failed', f'通知发送失败: {msg}')
        logger.warning('[Notify] 构建#%s 发版通知发送失败: %s', build_no, msg)
    return ok, msg


def trigger_release_notify(build_id, deploy_status=None, deploy_error=''):
    """后台线程发送通知（不阻塞构建回调/部署流程）"""
    try:
        app = current_app._get_current_object()
    except RuntimeError:
        logger.warning('[Notify] 无应用上下文，跳过构建#%s 发版通知', build_id)
        return
    t = threading.Thread(
        target=_run,
        args=(app, build_id, deploy_status, deploy_error),
        daemon=True,
    )
    t.start()


def _run(app, build_id, deploy_status, deploy_error):
    """后台线程：独立应用上下文重查构建并发送"""
    with app.app_context():
        from modules.cicd.models import Build
        from core.redis_client import get_redis, set_if_absent

        build = Build.query.get(build_id)
        if not build:
            logger.warning('[Notify] 构建#%s 不存在，跳过发版通知', build_id)
            return
        # 防重：同一构建只通知一次（Redis 不可用时直接放行，不因缓存故障丢通知）
        try:
            if get_redis() is not None and not set_if_absent(
                    f'build:notify:{build.build_no}', '1', ttl=7 * 24 * 3600):
                logger.info('[Notify] 构建#%s 已发送过发版通知，跳过', build.build_no)
                return
        except Exception as e:
            logger.warning('[Notify] 通知防重检查失败（继续发送）: %s', e)
        try:
            notify_release(build, deploy_status=deploy_status, deploy_error=deploy_error)
        except Exception as e:
            logger.exception('[Notify] 构建#%s 发版通知异常: %s', build_id, e)
            try:
                from modules.cicd.services.build_service import update_step_by_key
                update_step_by_key(build.build_no, 'notify', 'failed', f'通知异常: {e}')
            except Exception:
                pass


def send_test_message():
    """设置页「发送测试」：用系统设置里的 Webhook 发一张示例卡片。
    返回 (ok, message)
    """
    from modules.system.settings_service import get_setting
    url = (get_setting('feishu_webhook_url', '') or '').strip()
    secret = (get_setting('feishu_webhook_secret', '') or '').strip()
    if not url:
        return False, '请先配置飞书 Webhook 地址并保存'
    if not url.startswith(('http://', 'https://')):
        return False, 'Webhook 地址需以 http:// 或 https:// 开头'

    card = {
        'msg_type': 'interactive',
        'card': {
            'config': {'wide_screen_mode': True},
            'header': {
                'template': 'blue',
                'title': {'tag': 'plain_text', 'content': '🔔 发版通知测试'},
            },
            'elements': [
                {'tag': 'div', 'fields': [
                    _field('来源', '运维平台'),
                    _field('时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                ]},
                {'tag': 'div', 'text': {'tag': 'lark_md',
                                        'content': '这是一条测试消息。收到说明 Webhook 配置正确，发版完成后会自动推送结果卡片。'}},
                {'tag': 'note', 'elements': [{'tag': 'plain_text', 'content': '运维平台 · CI/CD 通知'}]},
            ],
        },
    }
    return send_card(url, secret, card)
