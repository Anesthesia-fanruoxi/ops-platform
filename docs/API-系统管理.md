# API - 系统管理

> 认证方式与通用响应见 [API文档.md](API文档.md)。

## 1. 认证与鉴权

### 登录

```text
POST /api/auth/login
```

支持本地账号密码、SSO 单步/两步、双因子登录，由平台配置的 `login_methods` 决定。

**本地登录请求体**

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

### 双因子第二步

```text
POST /api/auth/login-2fa
```

密码校验通过且用户启用了 TOTP 时，返回中间态，前端引导输入 6 位动态码后调用本接口完成登录。

### 超级管理员登录

```text
POST /api/auth/admin-login
```

`super_admins` 独立账号本地登录（本地逃生入口，仅系统管理权限）。

### 登出 / 当前用户 / 修改密码

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/logout` | 登出，失效当前 token |
| GET | `/api/auth/me` | 当前登录用户信息（含权限） |
| POST | `/api/auth/change-password` | 修改密码（校验平台密码规则，失效该用户全部会话） |

## 2. 用户管理 `/api/users`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/users/list` | 用户列表（子序列模糊搜索） |
| POST | `/api/users/update/<id>` | 更新用户（昵称/角色/启用状态） |
| POST | `/api/users/sync` | 同步认证中心用户 |
| GET | `/api/users/synced` | 认证中心用户只读副本列表 |
| POST | `/api/users/profile/<id>` | 修改用户资料 |
| POST | `/api/users/totp-setup/<id>` | TOTP 密钥管理 |

> 说明：创建 / 删除 / 重置密码接口已禁用（用户以认证中心为准，本地不管理账号生命周期）。

## 3. 角色管理 `/api/roles`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/roles/list` | 角色列表 |
| GET | `/api/roles/detail/<id>` | 角色详情 |
| POST | `/api/roles/create` | 创建角色 |
| POST | `/api/roles/update/<id>` | 更新角色（权限变更会失效相关用户会话） |
| POST | `/api/roles/delete/<id>` | 删除角色 |
| GET | `/api/roles/permissions` | 全部权限码（权限树） |

## 4. 系统设置 `/api/settings`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/settings/list?type=deploy\|nginx\|middleware\|platform` | 按标签页分组返回；不带 type 返回全部 |
| POST | `/api/settings/update` | 批量更新设置（密码留空不修改；`agent_comm_secret` 只读） |
| GET | `/api/settings/debug` | 调试：返回全部设置（含密码） |
| POST | `/api/settings/test-ssh` | SSH 连接测试 |
| POST | `/api/settings/test-k8s-ssh` | K8s Master SSH 连接测试 |
| POST | `/api/settings/test-nginx-ssh` | Nginx SSH 连接测试 |
| POST | `/api/settings/test-harbor` | Harbor 连接测试 |

## 5. 审计 `/api/audit`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audit/list` | 审计日志分页筛选查询 |
| GET | `/api/audit/modules` | 审计模块枚举 |

## 6. 仪表盘 `/api/dashboard`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/dashboard/stats` | 首页聚合统计（项目/环境/构建等计数） |

## 7. 监控 `/api/dashboard/monitor`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/dashboard/monitor/health` | 整体健康状态 |
| GET | `/api/dashboard/monitor/<key>` | 单卡监控详情 |
| GET | `/api/dashboard/monitor/stream` | SSE 实时推送监控数据 |

## 8. 菜单 `/api/menus`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/menus` | 当前用户可见菜单树 |
