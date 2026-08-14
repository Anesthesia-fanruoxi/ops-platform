# CI/CD 模块

> 覆盖：构建流程模板、凭据、Dockerfile 模板、Agent 节点、调度、构建执行、自动部署、调度中心实时看板

## 功能概览

| 子功能 | 说明 |
|---|---|
| 流程模板 | 项目级分步构建配置（Git 拉取 → 编译 → 产物收集 → Docker 构建/推送），前后端双配置结构 |
| 凭据管理 | password / token / ssh_key / harbor 四类，AES 加密落库，读取时解密 |
| Dockerfile 模板 | 可复用模板（java/node/go 等），占位符渲染 + 实时预览 |
| Agent 节点 | 注册、心跳、指标采集、SSH 安装/卸载/更新、禁用启用、日志与指标代理 |
| 调度 | 评分选优、排队、重跑钉住原节点、调度决策日志 |
| 构建 | 全量/部分构建、步骤状态、日志 SSE、取消、重跑 |
| 自动部署 | 构建成功后改远程 YAML 镜像 tag + `kubectl apply` |
| 调度中心 | 概览 SSE、调度日志、节点评分，实时看板 |

## Agent 通信协议

- 传输：AES-256-GCM 认证加密 + gzip 压缩；身份 = Agent name（去掉 token）。
- 共享密钥：`agent_comm_secret`（系统设置 → 平台设置，只读）。
- 端点（`/api/cicd/agent/`，白名单免登录）：
  - `register`：注册/更新节点与指标
  - `heartbeat`：每 5s 上报心跳与动态指标
  - `poll`：轮询领取构建
  - `build/<id>/step`：步骤状态回调
  - `build/<id>/result`：构建终态回传，成功后触发自动部署

## 调度机制

- 选优评分：容量 / CPU / 内存 / 磁盘 IO 加权（`dispatch_service.compute_score`）。
- 防重复派发：Redis 分布式锁（`lock:dispatch`）+ 构建领取 SETNX（`build:claim:{id}`），跨 worker 原子。
- 排队：无可用节点时保持 `pending`，心跳/构建完成时触发重新派发。
- 重跑：钉住原节点（构建目录在节点磁盘上），支持指定起始步骤。
- 调度日志：每次派发决策记录到 `cicd_schedule_logs`，可回溯评分与选优过程。

## Redis 关联

- Agent 心跳缓存 `agent:{id}:hb`（TTL 60s，DB 指标 30s 节流落库）。
- 调度概览缓存 `schedule:overview`（TTL 2s，多 SSE 客户端共享）。
- 在线判定、Docker 缓存大小读取均优先 Redis，降级回 DB。
- 构建领取锁 `build:claim:{id}`、派发锁 `lock:dispatch`，详见 Redis 使用说明。

## 核心表

| 表 | 说明 |
|---|---|
| `cicd_credentials` | 凭据（type/username/secret 密文/url） |
| `cicd_dockerfile_templates` | Dockerfile 模板 |
| `cicd_flow_templates` | 项目构建流程模板（1:1 项目） |
| `cicd_agents` | 构建节点（状态/指标/SSH/Harbor 配置） |
| `cicd_builds` | 构建记录（状态/快照/日志路径） |
| `cicd_schedule_logs` | 调度决策日志 |

## 主要接口

**流程模板**（`/api/cicd/templates`）

- `GET/POST /`：列表 / 创建
- `GET/PUT/DELETE /<id>`：详情 / 更新 / 删除

**凭据**（`/api/cicd/credentials`）

- `GET/POST /`：列表 / 创建
- `GET/PUT/DELETE /<id>`：详情 / 更新 / 删除

**Dockerfile 模板**（`/api/cicd/dockerfiles`）

- `GET/POST /`：列表 / 创建
- `GET/PUT/DELETE /<id>`：详情 / 更新 / 删除
- `GET /<id>/preview`：占位符渲染预览

**Agent 管理**（`/api/cicd/agents`）

- `GET /`：节点列表
- `GET /<id>/detail`：详情
- `POST /install`：建安装记录并返回共享密钥
- `POST /install-remote`：SSH 远程安装
- `GET /install-stream/<task_id>`：安装进度 SSE
- `POST /<id>/install|uninstall|reset|update|toggle-disable`：重装 / 卸载 / 重置 / 更新 / 禁用启用
- `GET /<id>/log|metrics|docker-cache`：日志 / 指标 SSE 代理 / Docker 缓存
- `PUT /<id>/config`：编辑节点配置
- `DELETE /<id>`：删除节点

**构建**（`/api/cicd/builds`）

- `GET/POST /`：列表 / 触发
- `GET /<id>`：详情
- `POST /<id>/cancel|rerun`：取消 / 重跑
- `GET /<id>/steps|steps/stream|log`：步骤 / 步骤 SSE / 日志
- `GET /branches|services`：分支 / 服务列表
- `GET /env/<id>` 与 `/env/<id>/stream`：环境视图 / 环境 SSE

**调度中心**（`/api/cicd/schedule`）

- `GET /overview|stream|logs|logs/<id>|scores`：概览 / 概览 SSE / 日志 / 日志详情 / 节点评分

**Agent 通讯协议**（`/api/cicd/agent`，白名单免登录）

- `POST /register|heartbeat|poll`：注册 / 心跳 / 领取构建
- `POST /build/<id>/step|result`：步骤回调 / 终态回传

## 关键文件

- `modules/cicd/services/`：
  - `build_service.py`：构建触发、取消、重跑、步骤状态落盘
  - `dispatch_service.py`：调度派发、评分选优、任务体组装
  - `agent_service.py`：节点配置 CRUD、Redis 心跳 / 在线 / 负载
  - `install_service.py`：SSH 远程安装 / 卸载 / 更新 Agent
  - `auto_deploy.py`：构建成功自动改 YAML tag 并 kubectl apply
  - `build_log.py`：日志分片追加 + SSE tail
  - `comm_crypto.py`：AES-GCM + gzip 加密通讯
  - `credential_service.py`：AES 加解密、Git 分支 / 凭据读取
  - `dockerfile_service.py`：Dockerfile 占位符渲染
- `agent/`：Go Agent 源码（`go build` 产物 `dist/cicd-agent`）
- `static/js/modules/cicd/CicdConfigPage.js`、`SchedulePage.js`：配置与调度中心前端
- `logs/cicd/`：构建日志（`{build_no}.log`、`{build_no}.deploy.log`）
