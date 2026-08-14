# API - 部署管理

> 认证方式与通用响应见 [API文档.md](API文档.md)。

## 1. 部署动作 `/api/deploy`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/deploy/execute/project` | 新增项目部署 |
| POST | `/api/deploy/execute/env` | 新增环境部署 |
| POST | `/api/deploy/execute/service` | 新增服务部署 |
| GET | `/api/deploy/stream` | 部署进度 SSE |
| GET | `/api/deploy/status` | 部署状态查询 |
| POST | `/api/deploy/recycle` | 回收环境 |
| POST | `/api/deploy/restore` | 恢复环境 |
| POST | `/api/deploy/permanent-delete` | 彻底删除环境 |
| POST | `/api/deploy/batch-recycle` | 批量回收 |
| POST | `/api/deploy/batch-restore` | 批量恢复 |
| POST | `/api/deploy/batch-permanent-delete` | 批量彻底删除 |

## 2. 环境管理 `/api/manage`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/manage/environments/list` | 环境列表 |
| GET | `/api/manage/environments/deleted` | 回收站列表 |
| GET | `/api/manage/environments/detail` | 环境详情 |
| POST | `/api/manage/environments/refresh` | 环境同步（远程下载 → 目录扫描 → 入库/清理） |
| GET | `/api/manage/environments/source-info` | 复制源环境信息 |
| GET | `/api/manage/environments/available-port` | 可用端口 |
| GET | `/api/manage/validate/project` | 项目名校验 |
| GET | `/api/manage/validate/environment` | 环境名校验 |
| GET | `/api/manage/validate/service` | 服务名校验 |

## 3. 项目管理 `/api/project`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/project/list` | 项目列表 |
| POST | `/api/project/update` | 更新项目 |
| POST | `/api/project/refresh` | 刷新项目 |

## 4. 管理辅助 `/api/admin`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/projects` | 项目列表 |
| POST | `/api/admin/projects` | 创建项目 |
| DELETE | `/api/admin/projects/<id>` | 删除项目 |
| GET | `/api/admin/projects/<id>/environments` | 项目下环境列表 |
| GET | `/api/admin/environments/<id>` | 环境详情 |
| PUT | `/api/admin/environments/<id>` | 更新环境 |
| DELETE | `/api/admin/environments/<id>` | 删除环境 |

## 5. 服务信息 `/api/deploy/service-info`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/deploy/service-info/list` | 服务列表 |
| GET | `/api/deploy/service-info/log/stream` | Pod 日志 SSE |
| GET | `/api/deploy/service-info/yaml` | 部署 YAML |
| GET | `/api/deploy/service-info/nacos/config` | Nacos 配置查看 |
| POST | `/api/deploy/service-info/nacos/config` | Nacos 配置发布 |

## 6. Harbor `/api/harbor`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/harbor/create-project` | 创建 Harbor 项目 |
| GET | `/api/harbor/list-projects` | 项目列表 |
| GET | `/api/harbor/get-project/<name>` | 项目详情 |
| DELETE | `/api/harbor/delete-project/<name>` | 删除项目 |
| GET | `/api/harbor/list-repositories/<project>` | 仓库列表 |
| GET | `/api/harbor/list-artifacts/<project>/<repo>` | 镜像制品列表 |
| POST | `/api/harbor/setup-cleanup` | 设置清理策略 |

## 7. Nacos `/api/nacos`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/nacos/list-namespaces` | 命名空间列表 |
| GET | `/api/nacos/get-namespace/<id>` | 命名空间详情 |
| POST | `/api/nacos/create-namespace` | 创建命名空间 |
| POST | `/api/nacos/copy-namespace` | 复制命名空间（含配置） |
| DELETE | `/api/nacos/delete-namespace/<id>` | 删除命名空间 |

## 8. NFS `/api/nfs`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/nfs/create-dirs` | 批量创建目录 |
| POST | `/api/nfs/check-dirs` | 批量校验目录 |
| POST | `/api/nfs/create-single-dir` | 单个创建目录 |
| POST | `/api/nfs/check-single-dir` | 单个校验目录 |
