# 运维平台 API 接口文档（总览）

> **基础信息**
> - 服务地址：`http://localhost:8050`（开发）/ `http://localhost:5000`（Docker）
> - API 版本：v2.0
> - 认证方式：`Authorization: Bearer {token}`（除白名单外所有 `/api/*` 均需认证）
> - 响应格式：JSON `{"code": 200, "msg": "success", "data": ...}`

## 认证与鉴权

- 登录成功后返回不透明 token，会话以 **Redis 为唯一存储**（MySQL 无认证表）。
- 每次有效请求自动**滑动续期**，过期时长由平台设置 `token_expire_hours` 控制（默认 8 小时）。
- 登出、修改密码、禁用/删除用户、角色权限变更会使对应会话失效。
- 同一用户名连续登录失败 5 次锁定 15 分钟（返回 429）。
- SSE 等无法携带 Header 的场景，可通过 `?token={token}` 传参。
- 白名单（免认证）：`/health`、`/api/auth/login`、`/api/auth/login-2fa`、`/api/auth/admin-login`、`/api/auth/logout`、`/api/cicd/agent/*`。

## 模块接口索引

| 模块 | 文档 | 说明 |
|---|---|---|
| 系统管理 | [API-系统管理.md](API-系统管理.md) | 认证 / 用户 / 角色 / 设置 / 审计 / 仪表盘 / 监控 / 菜单 |
| 部署管理 | [API-部署管理.md](API-部署管理.md) | 部署 / 环境 / 项目 / Harbor / Nacos / NFS / 服务信息 |
| Nginx | [API-Nginx.md](API-Nginx.md) | Nginx 配置管理 |
| CI/CD | [API-CICD.md](API-CICD.md) | 模板 / 凭据 / Dockerfile / Agent / 构建 / 调度 |
| 数据库工具 | [API-数据库工具.md](API-数据库工具.md) | 排序修复 / 结构对比同步 / DDL 同步 |

## 健康检查

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

## 通用响应格式

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
| 409 | 冲突（如实例任务进行中） |
| 429 | 登录尝试过多，已锁定 |
| 500 | 服务器内部错误 |
| 503 | 服务暂不可用（如认证服务 Redis 异常） |

## 附录：环境变量

详见 [README.md](../README.md)「配置说明」。常用：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `REDIS_URL` | redis://:redis@192.168.6.2:6380/1 | Redis 连接串 |
| `REDIS_ENABLED` | true | Redis 总开关 |
| `REDIS_KEY_PREFIX` | ops:platform: | Redis 键前缀 |
