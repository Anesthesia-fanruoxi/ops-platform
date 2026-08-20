# 范围边界：调度中心节点目录浏览

## 目标内（In Scope）

1. Agent 新增只读目录列举接口 `POST /list`（加密信封），节点侧路径管控（仅限 `cfg.WorkDir` 内，防 `../`/绝对路径/符号链接逃逸）
2. Master 新增转发接口 `GET /api/cicd/schedule/dirs`（`op:agent_dir`），经现有加密客户端转发
3. 新增独立权限码 `op:agent_dir`（查看节点目录），挂到调度中心菜单，角色可单独勾选
4. 调度中心前端目录浏览 UI（选节点 → 逐级浏览工作目录，面包屑 + 单层列表）
5. Agent 交叉编译（linux/amd64）并部署测试节点（保留旧二进制备回退）

## 目标外（Out of Scope）

1. 文件内容查看 / tail 日志（本次仅目录列举；后续可同边界扩展）
2. 目录写操作（上传/删除/重命名）——本功能严格只读
3. 工作目录之外的任何路径浏览（系统目录、其它项目目录）
4. SSH 直连方案（不采用）
5. 调度/派发逻辑、构建/取消/重跑逻辑（均不动）

## 涉及对象

| 类型 | 名称/路径 | 说明 |
| --- | --- | --- |
| 文件/模块 | `agent/server.go`、`modules/cicd/services/dispatch_service.py`、`modules/cicd/api/schedule_api.py`、`modules/cicd/routes.py`、`modules/system/menu_seed.py`、`static/js/modules/cicd/SchedulePage.js` | 仅允许修改这六个文件 |
| 环境 | 测试环境构建节点 | Agent 部署仅替换测试节点二进制，保留旧二进制备回退 |
| 数据 | menus 表 | 仅 op 码追加（`op:agent_dir`），不改表结构 |

## 变更记录

| 日期 | 变更内容 | 原因 |
| --- | --- | --- |
| 2026-08-14 | 初始范围确定 | 选 Agent 接口（节点侧管控）而非 SSH；只读单层目录；独立权限码 `op:agent_dir`；文件内容查看/写操作/工作目录外浏览均不做 |
