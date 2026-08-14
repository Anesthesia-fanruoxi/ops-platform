# API - CI/CD

> 认证方式与通用响应见 [API文档.md](API文档.md)。

## 1. 流程模板 `/api/cicd/templates`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cicd/templates` | 模板列表 |
| POST | `/api/cicd/templates` | 创建模板 |
| GET | `/api/cicd/templates/<id>` | 模板详情 |
| PUT | `/api/cicd/templates/<id>` | 更新模板 |
| DELETE | `/api/cicd/templates/<id>` | 删除模板 |

## 2. 凭据 `/api/cicd/credentials`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cicd/credentials` | 凭据列表 |
| POST | `/api/cicd/credentials` | 创建凭据（secret AES 加密落库） |
| GET | `/api/cicd/credentials/<id>` | 凭据详情 |
| PUT | `/api/cicd/credentials/<id>` | 更新凭据 |
| DELETE | `/api/cicd/credentials/<id>` | 删除凭据 |

## 3. Dockerfile 模板 `/api/cicd/dockerfiles`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cicd/dockerfiles` | 模板列表 |
| POST | `/api/cicd/dockerfiles` | 创建模板 |
| GET | `/api/cicd/dockerfiles/<id>` | 模板详情 |
| PUT | `/api/cicd/dockerfiles/<id>` | 更新模板 |
| DELETE | `/api/cicd/dockerfiles/<id>` | 删除模板 |
| GET | `/api/cicd/dockerfiles/<id>/preview` | 占位符渲染预览 |

## 4. Agent 节点 `/api/cicd/agents`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cicd/agents` | 节点列表 |
| GET | `/api/cicd/agents/<id>/detail` | 节点详情 |
| POST | `/api/cicd/agents/install` | 建安装记录并返回共享密钥 |
| POST | `/api/cicd/agents/install-remote` | SSH 远程安装 |
| GET | `/api/cicd/agents/install-stream/<task_id>` | 安装进度 SSE |
| POST | `/api/cicd/agents/<id>/install` | 重装 |
| POST | `/api/cicd/agents/<id>/uninstall` | 卸载 |
| POST | `/api/cicd/agents/<id>/reset` | 重置 |
| POST | `/api/cicd/agents/<id>/update` | 更新 |
| POST | `/api/cicd/agents/<id>/toggle-disable` | 禁用/启用 |
| GET | `/api/cicd/agents/<id>/log` | 日志代理 |
| GET | `/api/cicd/agents/<id>/metrics` | 指标 SSE 代理 |
| GET | `/api/cicd/agents/<id>/docker-cache` | Docker 缓存 |
| PUT | `/api/cicd/agents/<id>/config` | 编辑节点配置 |
| DELETE | `/api/cicd/agents/<id>` | 删除节点 |

## 5. 构建 `/api/cicd/builds`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cicd/builds` | 构建列表 |
| POST | `/api/cicd/builds` | 触发构建 |
| GET | `/api/cicd/builds/<id>` | 构建详情 |
| POST | `/api/cicd/builds/<id>/cancel` | 取消构建 |
| POST | `/api/cicd/builds/<id>/rerun` | 重跑构建 |
| GET | `/api/cicd/builds/<id>/steps` | 步骤状态 |
| GET | `/api/cicd/builds/<id>/steps/stream` | 步骤 SSE |
| GET | `/api/cicd/builds/<id>/log` | 构建日志 |
| GET | `/api/cicd/builds/branches` | 分支列表 |
| GET | `/api/cicd/builds/services` | 服务列表 |
| GET | `/api/cicd/builds/env/<id>` | 环境视图 |
| GET | `/api/cicd/builds/env/<id>/stream` | 环境 SSE |

## 6. 调度中心 `/api/cicd/schedule`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cicd/schedule/overview` | 调度概览 |
| GET | `/api/cicd/schedule/stream` | 概览 SSE |
| GET | `/api/cicd/schedule/logs` | 调度日志 |
| GET | `/api/cicd/schedule/logs/<id>` | 调度日志详情 |
| GET | `/api/cicd/schedule/scores` | 节点评分（不依赖 SSE） |

> `scores` 读取 MySQL 配置 + Redis 心跳，计算每个节点负载评分（越低越优，权重：容量 40% / CPU 30% / 内存 20% / 磁盘 IO 10%），在线节点按评分升序、离线节点排在最后。

## 7. Agent 通信协议 `/api/cicd/agent`（白名单免登录）

Agent 与 Master 使用 AES-256-GCM + gzip 加密，身份为节点 name，共享密钥 `agent_comm_secret`：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/cicd/agent/register` | 注册/更新节点与指标 |
| POST | `/api/cicd/agent/heartbeat` | 心跳（5s 一次，含动态指标） |
| POST | `/api/cicd/agent/poll` | 轮询领取构建 |
| POST | `/api/cicd/agent/build/<id>/step` | 步骤状态回调 |
| POST | `/api/cicd/agent/build/<id>/result` | 构建终态回调（成功后触发自动部署） |
