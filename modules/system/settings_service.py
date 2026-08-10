# -*- coding: utf-8 -*-
"""
系统设置读取（直连 MySQL，无 Redis 缓存）

业务配置统一从 settings 表读取；设置不存在时返回空。
"""
from modules.system.models import Setting


def get_setting(key, default=''):
    """读设置：直查 MySQL；不存在返回 default"""
    row = Setting.query.filter_by(key=key).first()
    return row.value if row else default


def get_setting_int(key, default=0):
    """读取整数型设置；缺省/非法返回 default"""
    raw = get_setting(key, '')
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def check_password_policy(password):
    """按平台设置校验密码强度，返回 (ok, error_msg)"""
    min_len = get_setting_int('password_min_length', 6)
    require_upper = str(get_setting('password_require_upper', '0')) in ('1', 'true')
    require_digit = str(get_setting('password_require_digit', '0')) in ('1', 'true')
    errors = []
    if not password or len(password) < min_len:
        errors.append(f'密码长度不能少于{min_len}位')
    if require_upper and not any(c.isupper() for c in password):
        errors.append('密码需包含大写字母')
    if require_digit and not any(c.isdigit() for c in password):
        errors.append('密码需包含数字')
    if errors:
        return False, '；'.join(errors)
    return True, ''
