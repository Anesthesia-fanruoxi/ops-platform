# -*- coding: utf-8 -*-
"""
项目配置
定义所有项目的固定配置参数
"""

# 项目列表
PROJECTS = {
    "ysh": {
        "name": "ysh",
        "services": [
            {"name": "app", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "auth", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "car", "xms": 1, "xmx": 8, "replicas": 1},
            {"name": "credit", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "credit-api", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "es", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "file", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "gateway", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "job", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "judgment", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "market", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "request", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "signature", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "sms", "xms": 1, "xmx": 8, "replicas": 1},
            {"name": "system", "xms": 2, "xmx": 8, "replicas": 1},
        ],
        "middleware": ["nacos", "mysql-nfs", "redis", "mysql", "rabbitmq"],
        "envs": {
            "dev": {
                "tag": "latest",
                "nacos_namespace": "0f4d4dc0-031b-481b-8801-ba126c28130d",
                "domain": "yshdev.hzbxhd.com",
                "debug_port": 33100,
                "node_port": 33130,
                "jmx_port": 33160,
                "middleware_port": 33190,
            },
            "test": {
                "tag": "latest",
                "nacos_namespace": "0f4d4dc0-031b-481b-8801-ba126c28130d",
                "domain": "yshdev.hzbxhd.com",
                "debug_port": 33200,
                "node_port": 33230,
                "jmx_port": 33260,
                "middleware_port": 33290,
            },
            "api": {
                "tag": "202607070901",
                "nacos_namespace": "9bd04ce8-9565-419c-bebe-93bd81411fbf",
                "domain": "yshapi.hzbxhd.com",
                "debug_port": 43300,
                "node_port": 43330,
                "jmx_port": 43360,
                "middleware_port": 43390,
            },
            "uat": {
                "tag": "latest",
                "nacos_namespace": "0f4d4dc0-031b-481b-8801-ba126c28130d",
                "domain": "yshdev.hzbxhd.com",
                "debug_port": 33300,
                "node_port": 33330,
                "jmx_port": 33360,
                "middleware_port": 33390,
            },
        }
    },
    "jxh": {
        "name": "jxh",
        "services": [
            {"name": "app", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "auth", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "credit", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "credit-api", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "es", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "file", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "gateway", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "job", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "judgment", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "market", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "signature", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "sms", "xms": 1, "xmx": 8, "replicas": 1},
            {"name": "system", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "request", "xms": 2, "xmx": 4, "replicas": 1},
        ],
        "middleware": ["nacos", "mysql-nfs", "redis", "mysql", "rabbitmq"],
        "envs": {
            "dev": {
                "tag": "latest",
                "nacos_namespace": "0f4d4dc0-031b-481b-8801-ba126c28130d",
                "domain": "jxhdev.hzbxhd.com",
                "debug_port": 33100,
                "node_port": 33130,
                "jmx_port": 33160,
                "middleware_port": 33190,
            },
            "test": {
                "tag": "latest",
                "nacos_namespace": "0f4d4dc0-031b-481b-8801-ba126c28130d",
                "domain": "jxhtest.hzbxhd.com",
                "debug_port": 33200,
                "node_port": 33230,
                "jmx_port": 33260,
                "middleware_port": 33290,
            },
            "api": {
                "tag": "latest",
                "nacos_namespace": "0f4d4dc0-031b-481b-8801-ba126c28130d",
                "domain": "jxhapi.hzbxhd.com",
                "debug_port": 33400,
                "node_port": 33430,
                "jmx_port": 33460,
                "middleware_port": 33490,
            },
        }
    },
    "xafq": {
        "name": "xafq",
        "services": [
            {"name": "app", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "auth", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "credit", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "credit-api", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "es", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "file", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "gateway", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "job", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "judgment", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "market", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "signature", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "sms", "xms": 1, "xmx": 8, "replicas": 1},
            {"name": "system", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "request", "xms": 2, "xmx": 4, "replicas": 1},
        ],
        "middleware": ["nacos", "mysql-nfs", "redis", "mysql", "rabbitmq"],
        "envs": {
            "dev": {
                "tag": "latest",
                "nacos_namespace": "89f4927a-bd13-4539-b629-e9ccaeab3b12",
                "domain": "devxafq.hzbxhd.com",
                "debug_port": 30100,
                "node_port": 30130,
                "jmx_port": 30160,
                "middleware_port": 30190,
            },
            "test": {
                "tag": "202309140957",
                "nacos_namespace": "168e12d3-437e-429b-995d-2751ce3495e0",
                "domain": "testxafq.hzbxhd.com",
                "debug_port": 30200,
                "node_port": 30230,
                "jmx_port": 30260,
                "middleware_port": 30290,
            },
        }
    },
    "ddfq": {
        "name": "ddfq",
        "services": [
            {"name": "app", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "auth", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "credit", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "credit-api", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "es", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "file", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "gateway", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "job", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "judgment", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "market", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "signature", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "sms", "xms": 1, "xmx": 8, "replicas": 1},
            {"name": "system", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "request", "xms": 2, "xmx": 4, "replicas": 1},
        ],
        "middleware": ["nacos", "mysql-nfs", "redis", "mysql", "rabbitmq"],
        "envs": {
            "dev": {
                "tag": "202310231725",
                "nacos_namespace": "0106f30b-5df5-4fab-9142-400a01e8269a",
                "domain": "ddfqdev.hzbxhd.com",
                "debug_port": 31100,
                "node_port": 31130,
                "jmx_port": 31160,
                "middleware_port": 31190,
            },
            "test": {
                "tag": "202310231725",
                "nacos_namespace": "9e59f272-e81c-4b3c-b0f8-469f49834bbf",
                "domain": "ddfqtest.hzbxhd.com",
                "debug_port": 31200,
                "node_port": 31230,
                "jmx_port": 31260,
                "middleware_port": 31290,
            },
        }
    },
    "ryh": {
        "name": "ryh",
        "services": [
            {"name": "app", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "auth", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "credit", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "credit-api", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "es", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "file", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "gateway", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "job", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "judgment", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "market", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "signature", "xms": 2, "xmx": 4, "replicas": 1},
            {"name": "sms", "xms": 1, "xmx": 8, "replicas": 1},
            {"name": "system", "xms": 2, "xmx": 8, "replicas": 1},
            {"name": "request", "xms": 2, "xmx": 4, "replicas": 1},
        ],
        "middleware": ["nacos", "mysql-nfs", "redis", "mysql", "rabbitmq"],
        "envs": {
            "dev": {
                "tag": "202309140957",
                "nacos_namespace": "3eece9af-f997-4ade-a767-959f6d7e80c1",
                "domain": "ryhdev.hzbxhd.com",
                "debug_port": 32100,
                "node_port": 32130,
                "jmx_port": 32160,
                "middleware_port": 32190,
            },
            "test": {
                "tag": "202309140957",
                "nacos_namespace": "7ca9e59d-5831-4f63-94a0-dee0c7e93619",
                "domain": "ryhtest.hzbxhd.com",
                "debug_port": 32200,
                "node_port": 32230,
                "jmx_port": 32260,
                "middleware_port": 32290,
            },
        }
    },
}


def get_project_config(project_name):
    """
    获取项目配置

    Args:
        project_name: 项目名称

    Returns:
        dict: 项目配置，不存在则返回None
    """
    return PROJECTS.get(project_name)


def get_project_env_config(project_name, env_name):
    """
    获取项目环境配置

    Args:
        project_name: 项目名称
        env_name: 环境名称

    Returns:
        dict: 环境配置，不存在则返回None
    """
    project = PROJECTS.get(project_name)
    if not project:
        return None
    return project.get('envs', {}).get(env_name)


def get_all_projects():
    """
    获取所有项目列表

    Returns:
        list: 项目列表
    """
    return list(PROJECTS.keys())


def get_project_envs(project_name):
    """
    获取项目的所有环境

    Args:
        project_name: 项目名称

    Returns:
        list: 环境列表
    """
    project = PROJECTS.get(project_name)
    if not project:
        return []
    return list(project.get('envs', {}).keys())
