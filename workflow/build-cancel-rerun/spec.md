# 构建取消链路修复 + 指定步骤重跑逻辑修复

> 状态：规划中（待确认）。边界见 [scope.md](./scope.md)。通用规则见 [../workflow.md](../workflow.md)。

## 任务目标

取消构建能真正终止运行中的操作（含 BuildKit docker build）；取消的构建不被回调复活；重跑逻辑堵住部署步骤空转与重复触发。

## 现状审查结论

### 取消链路（架构合理，4 个缺陷）

| # | 问题 | 位置 | 后果 |
| --- | --- | --- | --- |
| 1 | BuildKit 构建无法中断 | `agent/exec.go` 仅 `docker run` 注入容器名 | docker_build 阶段取消只杀 CLI 客户端，buildkitd 后台继续构建完 |
| 2 | 取消的构建被回调复活 | `build_service.complete_build` 无条件覆盖 status | 竞态下 cancelled 被覆盖成 success，还会触发自动部署 |
| 3 | `task.CancelRequested` 下发但从未消费 | `agent/build.go` 只定义未使用 | push_cancel 失败/任务在途时，取消的构建仍被完整执行 |
| 4 | handleCancel 同步 docker stop 阻塞 | `agent/cancel.go` / `agent/server.go` | docker stop 10s 宽限 > CMDB 5s 超时误记推送失败；runner nil 时误报 ok |

次要：`stopOp` 用裸 `docker` 命令，与 `checkDocker` 优先 `/usr/bin/docker` 不一致（systemd 精简 PATH 下可能找不到）。

### 重跑逻辑（校验完善，2 个缺陷 + 1 个体验问题）

| # | 问题 | 位置 | 后果 |
| --- | --- | --- | --- |
| 5 | 后端可从部署步骤重跑 | `rerun_build` 校验 1~6，Agent 只执行 1~5 | start_step=6 时 Agent 空转报 success，靠 `trigger_auto_deploy` 副作用触发部署，链路隐晦脆弱 |
| 6 | pending 状态可重复触发重跑 | `rerun_build` 未拦截 pending | 连续点击覆盖 build.json 与领取标记，产生竞态 |
| 7 | 原节点离线永久 pending | 调度钉住原节点无超时 | 重跑任务静默排队，无提示（体验问题，低优先级，本次不做） |

合理之处（不动）：kill 幂等与 register 竞态处理、`errBuildCancelled` 哨兵、pending 直接取消路径、步骤 5 重跑无镜像的友好报错、前端 4 步定义前后端一致。

## 涉及文件

| 文件 | 改动 |
| --- | --- |
| `agent/exec.go` | docker build 注入 `DOCKER_BUILDKIT=0`（杀客户端即中断） |
| `agent/cancel.go` | `stopOp` docker 路径与 `checkDocker` 统一 |
| `agent/server.go` | `handleCancel` 改异步 kill、runner 不存在返回 ok:false |
| `agent/build.go` | `executeBuild` 开头检查 `task.CancelRequested`，为 true 直接上报取消返回 |
| `modules/cicd/services/build_service.py` | `complete_build` 拒绝覆盖 cancelled；`rerun_build` 禁止部署步骤重跑、拦截 pending 重复触发 |

## 阶段规划

### 阶段一：Agent 取消终止能力

- [ ] `exec.go`：docker build 命令注入 `DOCKER_BUILDKIT=0`，回退 legacy builder（杀客户端即中断构建）
- [ ] `cancel.go`：`stopOp` 的 docker 二进制路径与 `checkDocker` 统一（优先 `/usr/bin/docker`）
- [ ] `server.go`：`handleCancel` 改 `go runner.kill()` 异步执行立即响应；runner 为 nil 返回 ok:false
- 检查点：`go build` 编译通过

### 阶段二：取消意图贯通与状态保护

- [ ] `build.go`：`executeBuild` 开头检查 `task.CancelRequested`，为 true 直接 sendResult 取消并返回
- [ ] `build_service.py`：`complete_build` 遇 status='cancelled' 拒绝覆盖（防复活 + 防误触发自动部署）
- 检查点：模拟 push_cancel 失败场景，构建启动即自终止；cancelled 记录不被回调覆盖

### 阶段三：重跑逻辑修复

- [ ] `rerun_build`：后端 start_step 等于部署步骤（6）时拒绝并提示（部署非 Agent 步骤）
- [ ] `rerun_build`：status='pending'（已入队未领取）时拒绝重复触发
- 检查点：接口层验证两类请求被正确拦截并返回明确错误信息

### 阶段四：Agent 编译部署与回归验证

- [ ] 交叉编译 linux 版 agent 并部署到节点
- [ ] 实测：触发真实构建，在 clone/编译/docker_build 各阶段取消，确认即时终止且状态为失败（错误信息"构建已取消"）
- [ ] 实测：各步骤重跑正常（含步骤 5 复用镜像路径）
- 检查点：验收标准全过

## 检查点与回滚

| 检查点 | 判定标准 | 未通过时的处理 |
| --- | --- | --- |
| 阶段一完成 | 编译通过 | 单文件改动，直接回滚 |
| 阶段二完成 | 取消意图全链路贯通 | complete_build 保护可独立回滚 |
| 阶段三完成 | 重跑拦截生效 | 校验逻辑独立，回滚不影响主流程 |
| 阶段四完成 | 实测取消/重跑全通过 | 保留旧 agent 二进制，可快速回退 |

## 验收标准

- [ ] clone/编译/docker_build 三个阶段取消均能即时终止，容器被 stop、状态为失败且错误信息为"构建已取消"
- [ ] 取消的构建不被 Agent 回调复活成 success
- [ ] 部署步骤重跑、pending 重复重跑被正确拦截
- [ ] 各步骤正常重跑不受影响（含步骤 5 复用镜像）

## 进度记录

| 日期 | 进展 | 问题与决策 |
| --- | --- | --- |
| 2026-08-14 | 完成取消链路与重跑逻辑审查，规划就绪 | 取消链路 4 缺陷 + 重跑 2 缺陷 1 体验问题；docker build 中断选 DOCKER_BUILDKIT=0 方案；部署步骤重跑定为拒绝 |
