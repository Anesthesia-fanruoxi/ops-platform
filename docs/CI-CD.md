# CI/CD 模块

> 覆盖：构建流程模板、凭据、Dockerfile 模板、Agent 节点、调度、构建执行、自动部署、调度中心

## 功能概览

| 子功能 | 说明 |
|---|---|
| 流程模板 | 项目级分步构建配置（Git 拉取 → 编译 → 产物收集 → Docker 构建/推送） |
| 凭据管理 | password / token / ssh_key / harbor 四类，AES 加密落库 |
| Dockerfile 模板 | 可复用模板（java/node/go，占位符渲染） |
| Agent 节点 | 注册、心跳、指标采集、SSH 安装/更新、禁用 |
| 调度 | 评分选优、排队、重跑钉住原节点、调度日志 |
| 构建 | 全量/部分构建、步骤状态、日志 SSE、取消、重跑 |
| 自动部署 | 构建成功后改远程 YAML tag + kubectl apply |

## Agent 通信协议

- 传输：AES-256-GCM 认证加密 + gzip 压缩；身份 = Agent name（去掉 token）。
- 共享密钥：`agent_comm_secret`（系统设置 → 平台设置，只读）。
- 端点（`/api/cicd/agent/`，白名单免登录）：
  - `register`：注册/更新节点与指标
  - `heartbeat`：每 5s 上报心跳与动态指标
  - `poll`：轮询领取构建（旧模式）
  - `build/<id>/step`：步骤状态回调
  - `build/<id>/result`：构建终态回调

## 调度机制

- 选优评分：容量 / CPU / 内存 / 磁盘 IO 加权（`dispatch_service.compute_score`）。
- 防重复派发：Redis 分布式锁（`lock:dispatch`）+ 构建领取 SETNX（`build:claim:{id}`），跨 worker 原子。
- 排队：无可用节点时保持 `pending`，心跳/构建完成时触发重新派发。
- 重跑：钉住原节点（构建目录在节点磁盘上），支持指定起始步骤。

## Redis 关联

- Agent 心跳缓存 `agent:{id}:hb`（TTL 60s，DB 指标 30s 节流落库）。
- 调度概览缓存 `schedule:overview`（TTL 2s，多 SSE 客户端共享）。
- 在线判定、Docker 缓存大小读取均优先 Redis，降级回 DB。

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

- `/api/cicd/templates`、`/api/cicd/credentials`、`/api/cicd/dockerfiles`
- `/api/cicd/agents`（管理）、`/api/cicd/agent`（Agent 协议）
- `/api/cicd/builds`（触发/取消/重跑/日志/步骤 SSE）
- `/api/cicd/schedule`（概览/SSE/日志）

## 关键文件

- `modules/cicd/services/`：build_service、dispatch_service、agent_service、install_service、auto_deploy、comm_crypto、build_log
- `agent/`：Go Agent 源码（`go build` 产物 `dist/cicd-agent`）
- `logs/cicd/`：构建日志（`{build_no}.log`、`{build_no}.deploy.log`）
