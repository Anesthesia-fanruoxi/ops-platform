# Nginx 配置管理模块

> 覆盖：Nginx 配置文件模板生成、MD5 校验、本地/远程同步

## 功能概览

| 子功能 | 说明 |
|---|---|
| 配置列表 | 查看所有托管配置（文件名/MD5/同步时间） |
| 模板生成 | 基于环境信息渲染 `nginx.conf.tpl` 生成站点配置 |
| MD5 校验 | 本地与远程文件一致性与变更检测 |
| 本地存储 | 配置保存在 `nginx_configs/` |
| 远程同步 | 推送/拉取远程 Nginx 服务器 `/etc/nginx/conf.d/` |

## 核心机制

- 配置内容存 MySQL `nginx_configs`，本地目录 `nginx_configs/` 为工作副本，远程通过 SSH 同步。
- 生成模板：`modules/deploy/templates/nginx.conf.tpl`（依赖部署模块的环境/域名/端口信息）。
- 服务器连接参数来自系统设置（nginx_server / ssh 端口 / 用户名 / 密码 / 目录）。

## 核心表

| 表 | 说明 |
|---|---|
| `nginx_configs` | file_name（唯一）/ content / md5 / synced_at |

## 主要接口

- `/api/nginx/configs`：配置列表、详情、保存
- `/api/nginx/generate`：按环境生成配置
- `/api/nginx/sync`：本地/远程同步

## 关键文件

- `modules/nginx/api.py` / `service.py` / `models.py`
- `modules/deploy/templates/nginx.conf.tpl`
- `nginx_configs/`（本地配置存储）
