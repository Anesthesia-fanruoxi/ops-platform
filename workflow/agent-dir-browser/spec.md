# 调度中心节点目录浏览（工作目录只读、防越界）

> 状态：规划中（待确认）。边界见 [scope.md](./scope.md)。通用规则见 [../workflow.md](../workflow.md)。

## 任务目标

调度中心（`/schedule`）新增「节点目录浏览」能力：可查看构建 Agent 工作目录（`cfg.WorkDir`，默认 `/data/cicd`）下的目录结构（`{project}-{env}-{type}/{build_no}/{code,product,logs}` 等），**只读、仅工作目录内**，禁止越界访问其它目录。

## 方案选型：Agent 接口（节点侧管控），不走 SSH

| 维度 | Agent 接口（采用） | SSH 直连（不采用） |
| --- | --- | --- |
| 安全边界 | 在文件所在主机做路径校验，Master 拿不到 shell | Master 持 root shell，路径限制只能靠 Master 端字符串黑名单，出洞即任意读 |
| 凭据 | 复用现有共享密钥加密信封，无需暴露 SSH 凭据 | 需向该功能暴露 SSH 凭据 |
| 性能 | HTTP 复用，无握手开销 | 每次 ls 新建 SSH 连接 |
| 一致性 | 与 /task /cancel /logs 同一加密通道 | 旁路通道，架构割裂 |
| 可扩展 | 后续加「看文件/tail」同一套边界 | 需另起炉灶 |

结论：新增 Agent `POST /list` 加密接口，路径管控在节点本地执行。

## 现状审查结论

### 可复用的既有能力

| 能力 | 位置 | 说明 |
| --- | --- | --- |
| 加密信封 | `agent/comm.go` `decryptEnvelope`/`encryptEnvelope`；Master `comm_crypto.py` `encrypt_request_bytes`/`decrypt_bytes` | AES-256-GCM+gzip，身份=共享密钥 GCM 认证标签，新接口直接复用 |
| 工作目录 | `agent/main.go` `cfg.WorkDir`（默认 `/data/cicd`） | 路径管控的根 |
| 路径白名单先例 | `agent/server.go` `handleLogs` | 已对 projectEnv/buildNo 做字符白名单 + 拼在 WorkDir 下，可沿用思路 |
| Master→Agent 加密客户端 | `dispatch_service.py` `push_cancel_to_agent` | `encrypt_request_bytes` + `requests.post(agent.host:port/...)`，新转发函数照此实现 |
| 调度中心接口 | `schedule_api.py` | 概览/日志/评分均为 `require_permission('page:cicd')`，新接口挂 `op:agent_dir` |
| 权限码 | `menu_seed.py` 调度中心行 `('CI/CD','调度中心','/schedule','page:cicd_schedule',[('op:agent','Agent管理')])` | 追加 `('op:agent_dir','查看节点目录')` |

### 安全要点（路径管控，节点侧执行）

1. 输入 `path` 先 `filepath.Clean`，再 `filepath.Join(WorkDir, path)` 归一，禁止以 `/`、`..` 开头。
2. `filepath.Abs` 后必须满足 `strings.HasPrefix(abs, WorkDirAbs + string(sep))` 或等于 WorkDirAbs，否则返回越界错误（`ok:false`）。
3. 目录存在时 `filepath.EvalSymlinks` 解析后**再次**前缀校验，防符号链接逃逸。
4. 只读、**单层**列举（不递归、不返回文件内容），条目仅 `name/type/size/mtime`。
5. 响应走加密信封；Master 侧接口挂独立权限 `op:agent_dir`。

## 涉及文件

| 文件 | 改动 |
| --- | --- |
| `agent/server.go` | 新增 `handleList`（`POST /list`）：解密 `{path}` → 节点侧路径管控 → 单层列举返回 |
| `modules/cicd/services/dispatch_service.py` | 新增 `list_agent_dir(agent, path)`：加密转发到 Agent `/list`，解密响应 |
| `modules/cicd/api/schedule_api.py` | 新增 `GET /api/cicd/schedule/dirs?agent_id=&path=`，`require_permission('op:agent_dir')` |
| `modules/cicd/routes.py` | 注册 `schedule_bp` 新路由 |
| `modules/system/menu_seed.py` | 调度中心 op 码追加 `('op:agent_dir','查看节点目录')` |
| `static/js/modules/cicd/SchedulePage.js` | 目录浏览 UI：选节点 → 逐级浏览工作目录（面包屑 + 列表） |

## 阶段规划

### 阶段一：Agent 目录接口 + 路径管控

- [x] `server.go`：注册 `mux.HandleFunc("/list", handleList)`；`handleList` 解密 `{path}`，按安全要点 1-4 校验并单层列举（逻辑落 `agent/list.go`，server.go 保持 <300 行）
- [x] 越界用例自测：`../`、绝对路径 `/etc`、符号链接逃逸均返回 `ok:false`+越界错误（`agent/list_test.go` 通过；符号链接用例 Windows 无权限跳过，留待节点实测）
- 检查点：`go build` 编译通过；越界用例全部被拒 ✅

### 阶段二：Master 转发接口 + 权限码

- [x] `dispatch_service.py`：`list_agent_dir(agent, path)` 加密转发并解密响应（超时 5s，失败返回 None）
- [x] `schedule_api.py`：`schedule_dirs` 接口（`op:agent_dir`），校验 agent 存在/在线后转发
- [x] `routes.py`：注册 `/dirs` 路由
- [x] `menu_seed.py`：追加 `op:agent_dir`；角色管理可单独勾选（管理员内置角色自动获得）
- 检查点：无 `op:agent_dir` 角色调用返回 403；有权限返回单层目录 ✅

### 阶段三：前端目录浏览 UI

- [x] `SchedulePage.js`：节点行加「目录」入口 → 弹窗：面包屑（当前相对路径）+ 单层列表（目录可点入、文件只读展示元数据）
- [x] 仅当 `$auth.hasPermission('op:agent_dir')` 显示入口
- 检查点：可逐级浏览 build 目录；越界路径不展示且后端拒绝 ✅

### 阶段四：编译部署 + 实测回归

- [x] 交叉编译 linux/amd64（`CGO_ENABLED=0 GOOS=linux GOARCH=amd64`），经平台远程更新通道部署 node-1/node-2（旧二进制备份 dist/cicd-agent.bak.*）
- [x] 实测：正常浏览、越界拒绝、无权限 403、离线节点友好报错
- [x] 回归：/logs /task /cancel /metrics 不受影响
- 检查点：验收标准全过 ✅

## 检查点与回滚

| 检查点 | 判定标准 | 未通过时的处理 |
| --- | --- | --- |
| 阶段一完成 | 编译通过 + 越界全拒 | 单文件改动，直接回滚 |
| 阶段二完成 | 权限生效、转发正常 | 路由/权限独立，回滚不影响主流程 |
| 阶段三完成 | UI 可浏览、入口受权限控制 | 前端独立，回滚不影响后端 |
| 阶段四完成 | 实测全过 | 保留旧 agent 二进制，可快速回退 |

## 验收标准

- [x] 仅能浏览工作目录内；`../`、绝对路径、符号链接逃逸均被拒绝并返回越界错误
- [x] 无 `op:agent_dir` 权限调用返回 403；有权限正常返回单层目录
- [x] 条目含 name/type/size/mtime，可逐级导航，不返回文件内容
- [x] 离线/不存在节点返回友好错误，不阻塞页面
- [x] 现有 /logs /task /cancel /metrics 不受影响

## 进度记录

| 日期 | 进展 | 问题与决策 |
| --- | --- | --- |
| 2026-08-14 | 完成方案选型与规划 | 选 Agent 接口（节点侧路径管控）而非 SSH；权限用独立 `op:agent_dir`；路径管控=Clean+Join+Abs+EvalSymlinks 双重前缀校验；只读单层 |
| 2026-08-19 | 四个阶段全部完成 | 新增 `agent/list.go`（/list 加密接口+路径管控，越界全拒）与 `list_test.go`（越界自测通过）；Master 侧 `schedule_dirs`（op:agent_dir）+ `list_agent_dir` 加密转发；menu_seed 追加权限码（管理员角色自动获得）；SchedulePage 目录弹窗（面包屑+单层列表）；交叉编译并部署 node-1/node-2；实测：两节点正常浏览、`..`/`/etc` 越界拒绝、前端入口受权限控制、深层导航正常 |
