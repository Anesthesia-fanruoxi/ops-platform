# -*- coding: utf-8 -*-
"""仓库风格 k8s YAML 映射（19 仓 script/k8s 抽取结果）"""
import json
import os

_MAP = None
_MAP_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'config', 'repo-k8s-service-map.json'
))


def load_map():
    global _MAP
    if _MAP is None:
        with open(_MAP_PATH, 'r', encoding='utf-8') as f:
            _MAP = json.load(f)
    return _MAP


def conventions():
    return load_map().get('conventions') or {}


def all_services():
    return list(load_map().get('services') or [])


def service_names():
    return [s.get('service') for s in all_services() if s.get('service')]


def get_service(name):
    for s in all_services():
        if s.get('service') == name:
            return s
    return None


def missing_services():
    return list(load_map().get('missing') or [])


def excluded_services():
    return list(load_map().get('excluded') or [])
