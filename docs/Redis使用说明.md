# Redis 使用说明（ops-platform）

> 定位：认证会话、登录限流、Agent 心跳、调度概览缓存、分布式锁、实例发现缓存。认证强依赖 Redis，其余功能 Redis 故障时降级不阻断业务。

## 一、部署与配置

- Redis 6+，外部实例 `192.168.6.2:6380`（需认证，db 1）。
- 键统一前缀：`ops:platform:`（不追加环境段）。
- 配置项：`REDIS_URL`、`REDIS_ENABLED`、`REDIS_KEY_PREFIX` 支持环境变量覆盖。
- 封装：`core/redis_client.py`，懒加载连接池，所有命令 `safe_*` 包装（Redis 异常返回 None/False 并记日志，不抛出到业务）。

## 二、使用范围

### 放入 Redis（加速 / 协调层）

| 数据 | 用途 | 类型 | TTL | 一致性策略 |
|---|---|---|---|---|
| 登录 Token 会话 | 认证会话唯一事实源（MySQL 无 `auth_tokens` 表） | STRING(JSON) | 滑动续期，默认 8h | 登录写、登出/改密/禁用/角色变更删除；Redis 不可用认证不可用 |
| 登录失败计数 | 连续失败锁定（默认 5 次 / 15min） | STRING(INCR) | 15min | 纯计数，可丢失 |
| Agent 心跳与动态指标 | 心跳只写 Redis，MySQL 仅存安装配置；在线 = 心跳键存在 | HASH | 60s | 键过期即离线；DB 指标 30s 节流落库 |
| Agent 并发负载 | 派发 +1 / 完成 -1 原子增减 | STRING | 60s | 随心跳更新 |
| 调度概览缓存 | 多 SSE 客户端共享一次计算 | STRING(JSON) | 2s | 短 TTL，允许秒级滞后 |
| pending 构建队列 | 原子弹出一致性领取 | ZSET | 随状态迁移删除 | 领取 SETNX 防重复；DB 状态为准 |
| 构建领取 / 状态 | 防重复派发、状态缓存 | STRING | 60s / 1h | DB 为准 |
| 分布式锁 | 派发、领取、部署、数据库任务串行 | STRING(SET NX PX) | 见锁语义 | 锁超时自动释放，持锁方续期 |
| MySQL 实例发现缓存 | 避免反复扫环境 + 读 YAML | STRING(JSON) | 60s | 短 TTL；不含密码字段 |

### 不放入 Redis（保持 MySQL / 文件系统）

- 业务终态数据：projects / environments / nginx_configs / cicd_* / collation_datasources / ddl_sync_* / roles / users / settings / menus / audit_logs 等，以 MySQL 为准。
- 敏感数据：密码哈希、Git/Harbor/SSH 凭据密文、`agent_comm_secret`、settings 中的密码类字段，默认不进 Redis。
- 构建日志内容：保持在文件系统（logs/），Redis 只放状态/进度。
- Nginx 配置内容：文件系统 + MySQL 为准。
- 系统设置：直连 MySQL，不做 Redis 缓存（设置量小、单键查询快）。

## 三、键设计

### 通用规则

- 统一前缀：`ops:platform:`，键格式 `ops:platform:{域}:{实体}:{字段}`，全小写冒号分段。
- 所有 key 必须带 TTL（除锁的过期即场景外），防止无限增长。
- 缓存类 key 统一 Cache-Aside：读穿透 + 写失效，MySQL 永远是唯一事实源。

### 键清单

| 域 | 键 | 说明 | TTL |
|---|---|---|---|
| auth | `ops:platform:auth:token:{token}` | 会话缓存：`{user_id, username, role_id, permissions[], expires_at}` | 8h（滑动） |
| auth | `ops:platform:auth:fail:{username}` | 登录失败次数 | 15min |
| auth | `ops:platform:auth:lock:{username}` | 登录锁定标记 | 15min |
| agent | `ops:platform:agent:{id}:hb` | 心跳 JSON：`{ts, load, cpu_load, mem_percent, disk_*, load1/5/15, net_*, docker_cache_size, sys_info}` | 60s |
| agent | `ops:platform:agent:{id}:load` | 当前并发负载 | 60s |
| build | `ops:platform:build:queue` | pending 队列（score=created_at，member=build_id） | 随状态迁移删除 |
| build | `ops:platform:build:claim:{id}` | 领取构建原子锁 | 60s |
| build | `ops:platform:build:{id}:status` | 状态缓存（pending/running/success/failed/cancelled） | 1h |
| schedule | `ops:platform:schedule:overview` | 调度概览缓存 JSON | 2s |
| lock | `ops:platform:lock:dispatch` | 派发任务全局锁 | 30s |
| lock | `ops:platform:lock:build:{id}` | 单构建状态迁移锁 | 60s |
| lock | `ops:platform:lock:deploy:{project}-{env}` | 同环境自动部署串行锁 | 10min |
| lock | `ops:platform:lock:database:{instance_id}` | 数据库工具任务实例锁 | 10min |
| lock | `ops:platform:lock:ddl_sync:{task_id}:{instance_id}` | DDL 同步监听防重锁（60s，每 20s 续约） | 60s |
| cache | `ops:platform:cache:database:instances` | MySQL 实例发现缓存 | 60s |

### 键值格式约定

- 结构化数据统一存 JSON 字符串；纯计数/标记用原子命令（INCR / SETNX）。
- 时间统一存 Unix 时间戳（秒）。
- 布尔统一存 `0/1`，与 MySQL 模型一致。

### 锁语义

- 统一用 `SET key value NX PX ttl` + 持锁 token 校验释放（Lua 脚本），防止误删他人锁。
- 所有锁必须有超时；长时间任务（部署、DDL 监听）需续期或使用足够大的 TTL。
- Redis 不可用时锁降级为进程内锁，保证不因 Redis 故障扩大并发风险。

## 四、降级策略

| 场景 | 降级行为 |
|---|---|
| 认证会话 | Redis 故障时认证不可用（无 DB 兜底），恢复后所有用户需重新登录 |
| 系统设置 | 直连 MySQL，无 Redis 依赖 |
| 分布式锁 | 降级为进程内锁（多 worker 下并发保护减弱） |
| 调度概览缓存 | 直接计算，业务不中断 |
| Agent 心跳/在线 | 回源 DB 判断，节流落库 |
| 实例发现缓存 | 直接扫描环境 + 读 YAML |
| DDL 同步监听 | Redis 不可用时不启动监听（宁可不同步） |

## 五、决策记录

**2026-08-04 已确认决策**：

1. Redis 部署：使用外部 Redis `192.168.6.2:6380`（db 1），本地 docker-compose 不新增 redis 服务。
2. 键前缀：`ops:platform:`，不追加环境段。
3. 实施范围：阶段 1–4 全部执行；SSE 跨 worker 实时推送（pub/sub）本期不做，保留 5s 轮询现状。
4. 敏感字段：密码/凭据类字段不进 Redis。
5. 认证改为纯 Redis：`auth_tokens` 表及模型已删除，登录会话只存 Redis；接受"Redis 重启后全部用户需重新登录"的取舍。
6. 设置缓存已取消：评估设置量小、查询快，`settings_service` 直连 MySQL。

**实施记录**：阶段 0（基础设施/封装/健康检查）、阶段 1（认证会话 + 登录限流）、阶段 3（Agent 心跳/概览缓存）、阶段 4（分布式锁/原子派发）均已落地，并完成真实 Redis 端到端验证（登录会话、心跳/在线判定、调度概览、分布式锁、登录限流全部实测通过）。
