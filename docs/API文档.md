# 运维平台 API 接口文档

> **基础信息**
> - 服务地址: `http://localhost:8050`（开发）/ `http://localhost:5000`（Docker）
> - API 版本: v2.0
> - 认证方式: `Authorization: Bearer {token}`（除白名单外所有 `/api/*` 均需认证）
> - 响应格式: JSON `{"code": 200, "msg": "success", "data": ...}`

---

## 目录

1. [认证与鉴权](#1-认证与鉴权)
2. [健康检查](#2-健康检查)
3. [系统管理](#3-系统管理)
4. [部署管理](#4-部署管理)
5. [Nginx 配置管理](#5-nginx-配置管理)
6. [CI/CD](#6-cicd)
7. [MySQL 排序修正](#7-mysql-排序修正)
8. [通用响应格式](#8-通用响应格式)
9. [附录：环境变量](#9-附录环境变量)

---

## 1. 认证与鉴权

### 认证说明

- 登录成功后返回不透明 token，会话以 **Redis 为唯一存储**（MySQL 无认证表）。
- 每次有效请求自动**滑动续期**，过期时长由平台设置 `token_expire_hours` 控制（默认 8 小时）。
- 登出、修改密码、禁用/删除用户、角色权限变更会使对应会话失效。
- 同一用户名连续登录失败 5 次锁定 15 分钟（返回 429）。
- SSE 等无法携带 Header 的场景，可通过 `?token={token}` 传参。
- 白名单（免认证）：`/health`、`/api/auth/login`、`/api/cicd/agent/*`。

### 1.1 登录

```text
POST /api/auth/login
```

**请求体**
```json
{"username": "admin", "password": "admin123"}
```

**响应**
```json
{
  "code": 200,
  "msg": "登录成功",
  "data": {
    "token": "xxxxxxxxxxxxxxxx",
    "expires_at": "2026-08-04 17:06:21",
    "user": {"id": 1, "username": "admin", "role_name": "管理员", "permissions": ["..."]}
  }
}
```

### 1.2 登出 / 当前用户 / 修改密码

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/logout` | 登出，失效当前 token |
| GET | `/api/auth/me` | 当前登录用户信息（含权限） |
| POST | `/api/auth/change-password` | 修改密码（校验平台密码规则，失效该用户全部会话） |

---

## 2. 健康检查

```text
GET /health
```

**响应**
```json
{
  "code": 200,
  "msg": "success",
  "data": {
    "status": "healthy",
    "timestamp": "2026-08-04T10:00:00.000000",
    "service": "ops-platform",
    "redis": "ok"
  }
}
```

`redis` 取值：`ok` / `down` / `disabled`。

---

## 3. 系统管理

### 3.1 用户管理 `/api/users`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users/list` | 用户列表 |
| POST | `/api/users/create` | 创建用户（校验密码规则） |
| POST | `/api/users/update/<id>` | 更新用户（昵称/角色/启用状态） |
| DELETE | `/api/users/delete/<id>` | 删除用户（同时失效其会话） |
| POST | `/api/users/reset-password/<id>` | 重置密码（失效该用户全部会话） |

### 3.2 角色管理 `/api/roles`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/roles/list` | 角色列表 |
| GET | `/api/roles/detail/<id>` | 角色详情 |
| POST | `/api/roles/create` | 创建角色 |
| POST | `/api/roles/update/<id>` | 更新角色（权限变更会失效相关用户会话） |
| DELETE | `/api/roles/delete/<id>` | 删除角色 |
| GET | `/api/roles/permissions` | 全部权限码 |

### 3.3 系统设置 `/api/settings`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings/list?type=deploy\|nginx\|middleware\|platform` | 按标签页分组返回；不带 type 返回全部 |
| POST | `/api/settings/update` | 批量更新设置（密码留空不修改；`agent_comm_secret` 只读） |
| GET | `/api/settings/debug` | 调试：返回全部设置（含密码） |
| POST | `/api/settings/test-ssh` / `test-k8s-ssh` / `test-nginx-ssh` / `test-harbor` | 连接测试 |

设置项按 `settings.type` 列分组（deploy/nginx/middleware/platform）；平台设置包含 Token 过期时间、密码规则、Agent 通讯密钥。

---

## 4. 部署管理

### 4.1 部署动作 `/api/deploy`

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/deploy/execute/project` | 新增项目部署（op:deploy_project） |
| POST | `/api/deploy/execute/env` | 新增环境部署（op:deploy_env） |
| POST | `/api/deploy/execute/service` | 新增服务部署（op:deploy_service） |
| GET | `/api/deploy/stream` | 部署进度 SSE |
| GET | `/api/deploy/status` | 部署状态 |
| POST | `/api/deploy/recycle` | 回收环境 |
| POST | `/api/deploy/restore` | 恢复环境 |
| POST | `/api/deploy/permanent-delete` | 彻底删除环境 |
| POST | `/api/deploy/batch-recycle` / `batch-restore` / `batch-permanent-delete` | 批量操作 |

### 4.2 环境管理 `/api/manage`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/manage/environments/list` | 环境列表 |
| GET | `/api/manage/environments/deleted` | 回收站列表 |
| GET | `/api/manage/environments/detail` | 环境详情 |
| GET | `/api/manage/environments/refresh` | 同步导入 |
| GET | `/api/manage/environments/source-info` / `available-port` | 复制源信息 / 可用端口 |
| POST | `/api/manage/validate/project` / `validate/environment` / `validate/service` | 名称校验 |

### 4.3 项目管理 `/api/project`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/project/list` | 项目列表 |
| POST | `/api/project/update` | 更新项目 |
| GET | `/api/project/refresh` | 刷新项目 |

### 4.4 管理接口 `/api/admin`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET/POST | `/api/admin/projects` | 项目列表 / 创建 |
| DELETE | `/api/admin/projects/<id>` | 删除项目 |
| GET | `/api/admin/projects/<id>/environments` | 项目下环境 |
| GET/POST/DELETE | `/api/admin/environments/<id>` | 环境查询/更新/删除 |

### 4.5 Harbor / Nacos / NFS

| 模块 | 路径 | 说明 |
|---|---|---|
| Harbor | `/api/harbor/create-project` | 创建 Harbor 项目 |
| Harbor | `/api/harbor/list-projects` | 项目列表 |
| Harbor | `/api/harbor/get-project/<name>` | 项目详情 |
| Harbor | `/api/harbor/delete-project/<name>` | 删除项目 |
| Harbor | `/api/harbor/list-repositories/<project>` | 仓库列表 |
| Harbor | `/api/harbor/list-artifacts/<project>/<repo>` | 镜像制品列表 |
| Harbor | `/api/harbor/setup-cleanup` | 设置清理策略 |
| Nacos | `/api/nacos/list-namespaces` | 命名空间列表 |
| Nacos | `/api/nacos/get-namespace/<id>` | 命名空间详情 |
| Nacos | `/api/nacos/create-namespace` | 创建命名空间 |
| Nacos | `/api/nacos/copy-namespace` | 复制命名空间（含配置） |
| Nacos | `/api/nacos/delete-namespace/<id>` | 删除命名空间 |
| NFS | `/api/nfs/create-dirs` / `check-dirs` | 项目目录创建/检查 |
| NFS | `/api/nfs/create-single-dir` / `check-single-dir` | 单目录创建/检查 |

---

## 5. Nginx 配置管理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/nginx/list` | 配置列表（文件名/MD5/同步时间） |
| GET | `/api/nginx/file/<id>` | 配置内容 |
| POST | `/api/nginx/sync` | 本地/远程同步 |
| POST | `/api/nginx/push/<id>` | 推送并 reload 远程 Nginx |

---

## 6. CI/CD

### 6.1 管理接口

| 前缀 | 说明 |
|---|---|
| `/api/cicd/templates` | 项目构建流程模板 CRUD |
| `/api/cicd/credentials` | 凭据 CRUD + 测试 |
| `/api/cicd/dockerfiles` | Dockerfile 模板 CRUD + 预览 |
| `/api/cicd/agents` | 节点管理（详情/指标/日志/安装/重装/卸载/重置/更新/禁用/Docker 缓存） |
| `/api/cicd/builds` | 构建（触发/详情/取消/重跑/步骤 SSE/日志/分支/服务列表） |
| `/api/cicd/schedule` | 调度中心（概览/SSE 推送/调度日志/**节点评分查询**） |

`GET /api/cicd/schedule/scores`：独立节点评分接口（不依赖 SSE）——读取 MySQL 配置 + Redis 心跳，
计算每个节点的负载评分（越低越优，权重：容量 40% / CPU 30% / 内存 20% / 磁盘IO 10%），在线节点按评分升序、离线节点排在最后。

### 6.2 Agent 通信协议（`/api/cicd/agent`，白名单免登录）

Agent 与 Master 使用 AES-256-GCM + gzip 加密，身份为节点 name，共享密钥 `agent_comm_secret`：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/cicd/agent/register` | 注册/更新节点与指标 |
| POST | `/api/cicd/agent/heartbeat` | 心跳（5s 一次，含动态指标） |
| POST | `/api/cicd/agent/poll` | 轮询领取构建 |
| POST | `/api/cicd/agent/build/<id>/step` | 步骤状态回调 |
| POST | `/api/cicd/agent/build/<id>/result` | 构建终态回调（成功后触发自动部署） |

---

## 7. MySQL 排序修正

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/database/instances` | 实例列表（自动 + 自定义） |
| GET | `/api/database/databases` | 实例数据库列表 |
| GET | `/api/database/tables/<database>` | 表列表 |
| GET | `/api/database/columns/<database>/<table>` | 字段列表 |
| GET | `/api/database/column_issues/<database>` | 字段问题清单 |
| GET/POST | `/api/database/datasources` | 自定义数据源列表/创建 |
| POST/DELETE | `/api/database/datasources/<id>` | 更新/删除数据源 |
| POST | `/api/database/datasources/test` | 连接测试 |
| POST | `/api/database/fix_database_async` / `fix_table_async` / `fix_all_tables_async` / `fix_columns_async` | 异步修复任务 |
| POST | `/api/database/compare_structure` | 表结构对比（源库→目标库） |
| POST | `/api/database/sync_structure_sql` | 预览同步 SQL（不执行） |
| POST | `/api/database/sync_structure_async` | 异步执行表结构同步 |
| GET | `/api/database/stream?task_key=` | 修复/同步进度 SSE |
| GET | `/api/database/report/<database>` | 校验报告下载 |

---

## 8. 通用响应格式

```json
{"code": 200, "msg": "success", "data": {}}
```

| code | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未登录或 Token 已过期 |
| 403 | 无操作权限 |
| 404 | 资源不存在 |
| 409 | 冲突（如同实例修复任务进行中） |
| 429 | 登录尝试过多，已锁定 |
| 500 | 服务器内部错误 |
| 503 | 服务暂不可用（如认证服务 Redis 异常） |

---

## 9. 附录：环境变量

详见 [README.md](../README.md)「配置说明」。常用：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `REDIS_URL` | redis://:redis@192.168.6.2:6380/1 | Redis 连接串 |
| `REDIS_ENABLED` | true | Redis 总开关 |
| `REDIS_KEY_PREFIX` | ops:platform: | Redis 键前缀 |
