# 范围边界：构建取消 + 重跑逻辑修复

## 目标内（In Scope）

1. 取消链路修复：docker build 可中断（DOCKER_BUILDKIT=0）、取消意图启动前检查、cancelled 状态防回调覆盖、handleCancel 异步化与如实上报、stopOp docker 路径统一
2. 重跑逻辑修复：禁止从部署步骤（后端第 6 步）重跑、拦截 pending 状态重复触发重跑
3. Agent 交叉编译（linux/amd64）产出部署包

## 目标外（Out of Scope）

1. 调度派发逻辑重构（dispatch_pending 择优/钉节点机制不动）
2. 原节点离线永久 pending 的超时通知（体验问题，仅记录，本次不做）
3. 前端构建步骤 UI 改动（仅后端行为修复）
4. 自动部署（auto_deploy）逻辑本身

## 涉及对象

| 类型 | 名称/路径 | 说明 |
| --- | --- | --- |
| 文件/模块 | `agent/exec.go`、`agent/cancel.go`、`agent/server.go`、`agent/build.go`、`modules/cicd/services/build_service.py` | 仅允许修改这五个文件 |
| 环境 | 测试环境构建节点 | Agent 部署仅替换测试节点二进制，保留旧二进制备回退 |
| 数据 | cicd_builds 表 | 仅状态字段读写，不改表结构 |

## 变更记录

| 日期 | 变更内容 | 原因 |
| --- | --- | --- |
| 2026-08-14 | 初始范围确定 | 取消链路审查发现 4 缺陷、重跑审查发现 2 缺陷 1 体验问题；体验问题（节点离线 pending）定为本次不做 |
| 2026-08-14 | scope 扩展：`modules/cicd/api/agent_comm_api.py`（1 行） | complete_build 防复活后，`agent_build_result` 仍按原始 status 判断触发自动部署，竞态下已取消构建会被误部署；改按 `build.status=='success'` 判定（验收标准「防误触发自动部署」必需） |
| 2026-08-14 | scope 扩展：`modules/cicd/api/build_api.py`（1 行） | rerun 成功路径原把成功消息当错误返回 400，前端重跑成功后误报红字错误；改 `if not build` 判定（验收标准「各步骤正常重跑不受影响」必需） |
