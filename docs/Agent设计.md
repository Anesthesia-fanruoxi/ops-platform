# Agent 设计（Go 构建节点）

> Agent 为 Go 编写的独立进程（`agent/`），由 Master 通过 SSH 安装/更新，负责在构建节点上执行构建任务并上报指标与状态。

## 定位

- 独立进程，运行在 Linux 构建节点上，固定端口 9090（日志/任务 HTTP 服务）。
- 与 Master 之间使用共享密钥（`agent_comm_secret`）做 AES-256-GCM 认证加密 + gzip 压缩通信。
- 由 Master 通过「调度中心 → 节点 → 安装」自动编译并下发 `dist/cicd-agent`。

## 编译

```bash
cd agent
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o dist/cicd-agent .
```

## 启动参数

| 参数 | 说明 |
|---|---|
| `--name` | 节点名称（必填） |
| `--secret` | 通信密钥（必填，与 Master 的 `agent_comm_secret` 一致） |
| `--master` | Master 地址（必填，如 `http://192.168.1.10:8050`） |
| `--workdir` | 工作目录（默认 `/data/cicd`） |
| `--advertise` | Master 回推地址（默认取主机名） |
| `--heartbeat` | 心跳间隔（秒，默认 5） |

固定值：`MaxConcurrent=1`（单并发）、`LogPort=9090`。

## 启动流程

1. 解析配置，创建 `workdir` 与 `logs` 目录。
2. 日志双写：stdout（journal）+ `{workdir}/logs/agent.log`（O_TRUNC 启动即截断）。
3. 打印运行环境检查：Docker 版本与数据目录、Harbor/Registry 登录状态、NFS 挂载、工作目录。
4. 启动实时指标采集（CPU/内存/磁盘 IO/网络）、Docker 构建缓存采集（30s 一次）、每天凌晨 1 点清理 3 天前缓存。
5. 采集静态配置（CPU 核数/内存总量/磁盘容量/OS/Docker 版本）。
6. `register()` 注册上线。
7. 启动日志/任务 HTTP 服务与心跳协程。
8. 收到 SIGINT/SIGTERM 后等待在跑任务完成再退出（`wg.Wait()`）。

## 目录结构

| 文件 | 职责 |
|---|---|
| `main.go` | 配置解析、启动、信号处理 |
| `master.go` | Master 通信（注册/心跳/回调/上报） |
| `comm.go` | AES-GCM 通讯加密 + gzip |
| `build.go` | 构建执行管线（clone → build → collect → docker_build → push） |
| `cancel.go` | 构建取消控制器（docker stop + 杀进程） |
| `exec.go` | 命令执行 + 步骤日志写入器 |
| `server.go` | HTTP 服务（任务接收/日志查询） |
| `metrics.go` | 实时指标采集（CPU/内存/磁盘 IO/网络） |
| `metrics_history.go` | 历史指标 Ring Buffer + `/metrics` 端点 |
| `sysinfo.go` | 静态配置采集（CPU/内存/OS/Docker 版本） |
| `disk_linux.go` / `disk_other.go` | Linux 磁盘容量采集（statfs）/ 非 Linux 占位 |

## 通信协议

Agent 与 Master 之间的接口位于 `/api/cicd/agent/`（白名单免登录，AES-GCM 加密）：

| 端点 | 方向 | 用途 |
|---|---|---|
| `POST /register` | Agent → Master | 凭 name 注册上线，上报静态配置 |
| `POST /heartbeat` | Agent → Master | 每 5s 上报心跳与动态指标 |
| `POST /poll` | Agent → Master | 轮询领取待派发构建 |
| `POST /build/<id>/step` | Agent → Master | 构建步骤状态回调 |
| `POST /build/<id>/result` | Agent → Master | 构建终态回传，成功后触发自动部署 |

身份识别：Agent name（去掉 token）。密钥在请求体中由 AES-GCM 加密，Master 用同一密钥解密校验。

## 构建执行管线

`build.go` 按项目流程模板分步执行：

```text
Git clone → 编译构建 → 产物收集 → Docker 构建 → 镜像推送 Harbor
```

- 每步状态通过 `build/<id>/step` 实时回传，日志经 `exec.go` 分片写文件并 SSE tail。
- 支持取消：`cancel.go` 通过 docker stop + 杀进程中断当前构建。
- 构建记录与目录保留数由节点配置 `keep_builds` 控制（默认 5），超出同步清理 Master 与节点目录。

## 指标与监控

- 实时指标：CPU、内存、磁盘 IO、网络，随心跳上报，DB 侧 30s 节流落库。
- 历史指标：Ring Buffer 内存保留，`/metrics` 端点供 Master 代理读取。
- Docker 构建缓存：30s 采集一次随心跳上报，供调度评分与缓存清理。

## 安装与更新

- 安装入口：调度中心 → 节点 → 安装，Master 通过 SSH 连接节点（凭据或密码认证），自动下发并启动 `cicd-agent`。
- 支持远程重装、卸载、重置、更新、禁用启用，安装进度通过 SSE 推送。
- 安装时自动配置 NFS 挂载（`nfs_server`/`nfs_share` → `frontend_mount_dir`）与 Harbor 凭据。

## 相关文档

- 调度与构建：`docs/CI-CD.md`
- 节点管理接口：`docs/API文档.md`
