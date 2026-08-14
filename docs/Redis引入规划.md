# Redis 引入规划（ops-platform）

> 状态：待确认。确认后按阶段执行，每阶段可独立上线、可回滚。

## 一、背景与目标

当前项目所有状态都落在 MySQL，且部署为多 worker（gunicorn -w 4）进程。存在几类典型问题：

1. **热路径反复查库**：每个 `/api/*` 请求都要查一次 `auth_tokens` + `users`；调度概览 SSE 每 5 秒/客户端全量查 Agent、构建队列；设置项被各模块零散 `Setting.query.filter_by(key=...)` 读取。
2. **高频写库**：每个 Agent 每 5 秒上报心跳，一次心跳更新 40+ 个字段并触发一次全量调度扫描（`dispatch_pending`）。
3. **进程内锁在多 worker 下失效**：`dispatch_service._dispatch_lock`、`auto_deploy._env_locks`、`collation.tasks._collation_tasks` 都是 `threading` 级别的，4 个 worker 之间互不可见，存在重复派发/同环境并发部署/任务状态丢失的竞态。
4. **SSE 实时推送无法跨 worker 广播**：当前靠 5 秒轮询 + 监听文件 mtime，实时性差且每客户端独立重复计算。

引入 Redis 的目标：**给热路径加缓存、给跨 worker 场景加原子协调能力，且 Redis 故障时全部降级回 MySQL/进程内锁，不影响业务可用性。**

## 二、哪些数据放入 Redis

### 2.1 放入 Redis（加速/协调层）

| # | 数据 | 现状 | Redis 方案 | 数据类型 | TTL | 一致性策略 |
|---|---|---|---|---|---|
| 1 | 登录 Token 会话 | 原每次 API 请求查 `auth_tokens` + `users` | **Redis 为唯一事实源**（MySQL `auth_tokens` 表已废弃删除）；登录写缓存，鉴权只读 Redis | STRING (JSON) | **滑动续期**：每次有效请求重置为 `TOKEN_EXPIRE_HOURS`（默认 8h），闲置 8h 过期 | 登录写、登出/改密/禁用/角色变更删除；Redis 不可用时认证不可用（无 DB 兜底） |
| 2 | 登录失败计数（限流） | 无防护 | 按用户名/IP 计数，超过阈值临时锁定 | STRING (INCR) | 15min 滑动 | 纯 Redis 计数，可丢失 |
| 3 | ~~系统设置缓存~~ | 多处 `Setting.query.filter_by(key=...)` | **已移除**：设置直连 MySQL，不做 Redis 缓存（设置量小、单键查询亚毫秒） | — | — | — |
| 4 | Agent 心跳与动态指标 | 每 5s 写库 40+ 字段 | 心跳**只写 Redis**（Hash），MySQL 仅存安装配置；在线 = Redis 心跳键存在 | HASH | 15s | 键过期即离线，无 DB 写入；负载由 Master 原子增减 |
| 5 | 调度概览缓存 | SSE 每 5s/客户端全量查库 | 概览 JSON 缓存 2s，多客户端共享一次计算 | STRING (JSON) | 2s | 短 TTL，允许秒级滞后 |
| 6 | pending 构建队列 | 每次派发全表扫 `status='pending'` | ZSET（score=创建时间），原子弹出一致性领取 | ZSET | 无（随构建状态迁移删除） | 领取时 SETNX 防重复；DB 状态为准 |
| 7 | 分布式锁 | 进程内 `threading.Lock` | 派发、领取构建、自动部署同环境串行、collation 任务 | STRING (SET NX PX) | 见 3.4 | 锁超时自动释放，持锁方续期 |
| 8 | collation 实例发现缓存 | 每次页面/任务全量扫 environments + 读 YAML | 实例列表缓存 60s | STRING (JSON) | 60s | 短 TTL；涉及密码字段不进缓存（见下） |
| 9 | SSE 广播频道（可选，阶段 5） | 5s 轮询 + 文件 mtime | pub/sub 频道，构建状态/心跳变化即推送 | PUB/SUB | 无 | 丢消息可接受，SSE 保留轮询兜底 |
| 10 | 构建进度/步骤状态（可选，阶段 5） | 写文件 build.json + 监听 mtime | 步骤状态同步写 Redis，SSE 直接读 | HASH | 构建生命周期 | 文件仍为主，Redis 为推送加速 |

### 2.2 不放入 Redis（保持 MySQL/文件系统）

- **业务终态数据**：projects / environments / nginx_configs / cicd_builds / cicd_credentials / collation_datasources / roles / users —— 以 MySQL 为准。
- **敏感数据**：密码哈希、Git/Harbor/SSH 凭据密文、`agent_comm_secret`、`settings` 中的密码类字段 —— **默认不进 Redis**（如确有需要，仅允许短 TTL + 应用层加密，见待确认事项）。
- **构建日志内容**：保持在文件系统（logs/），Redis 只放状态/进度。
- **Nginx 配置内容**：文件系统 + MySQL 为准。

## 三、Redis 键统一设计

### 3.1 通用规则

- 统一前缀：`ops:platform:`（若多环境共用实例，追加环境段，如 `ops:platform:prod:`，默认空）。
- 键格式：`ops:platform:{域}:{实体}:{字段}`，全部小写，冒号分段。
- 所有 key **必须带 TTL**（除 pub/sub 频道与锁的过期即场景外），防止无限增长。
- 缓存类 key 统一约定：读穿透 + 写失效（Cache-Aside），MySQL 永远是唯一事实源。

### 3.2 键清单

| 域 | 键 | 说明 | 类型 | TTL |
|---|---|---|---|---|
| auth | `ops:platform:auth:token:{token}` | 会话缓存：`{user_id, username, role_id, permissions[], expires_at}` | STRING | TOKEN_EXPIRE_HOURS |
| auth | `ops:platform:auth:fail:{username}` | 登录失败次数（连续失败锁定） | STRING | 15min |
| auth | `ops:platform:auth:lock:{username}` | 登录锁定标记 | STRING | 15min |
| setting | `ops:platform:setting:{key}` | 设置值缓存 | STRING | 1h |
| agent | `ops:platform:agent:{id}:hb` | 心跳 JSON：`{ts, load, cpu_load, mem_percent, disk_*, load1/5/15, net_*, docker_cache_size, sys_info}` | STRING | 60s |
| agent | `ops:platform:agent:{id}:load` | 当前并发负载（派发 +1 / 完成 -1 原子增减） | STRING | 60s |
| build | `ops:platform:build:queue` | pending 队列（score=created_at 时间戳，member=build_id） | ZSET | 随状态迁移删除 |
| build | `ops:platform:build:claim:{id}` | 领取构建的原子锁 | STRING | 60s |
| build | `ops:platform:build:{id}:status` | 状态缓存（pending/running/success/failed/cancelled） | STRING | 1h |
| build | `ops:platform:build:{id}:progress`（可选） | 步骤进度 JSON | STRING | 24h |
| schedule | `ops:platform:schedule:overview` | 调度概览缓存 JSON | STRING | 2s |
| sse | `ops:platform:sse:event`（可选） | 状态变化广播频道 | PUB/SUB | — |
| lock | `ops:platform:lock:dispatch` | 派发任务全局锁 | STRING | 30s |
| lock | `ops:platform:lock:build:{id}` | 单构建状态迁移锁 | STRING | 60s |
| lock | `ops:platform:lock:deploy:{project}-{env}` | 同环境自动部署串行锁 | STRING | 10min |
| lock | `ops:platform:lock:database:{instance_id}` | 数据库工具任务实例锁 | STRING | 10min |
| cache | `ops:platform:cache:database:instances` | MySQL 实例发现缓存 | STRING | 60s |
| rate | `ops:platform:rate:api:{path}:{ip}`（可选） | 接口级限流 | STRING | 60s |

### 3.3 键值格式约定

- 结构化数据统一存 JSON 字符串（便于调试与多语言互操作）；纯计数/标记用原子命令（INCR / SETNX）。
- 时间统一存 Unix 时间戳（秒），避免时区歧义。
- 布尔统一存 `0/1`，与现有 MySQL 模型保持一致。

### 3.4 锁语义

- 统一用 `SET key value NX PX ttl` + 持锁 token 校验释放（Lua 脚本），防止误删他人锁。
- 所有锁必须有超时；长时间任务（部署）需续期或使用足够大的 TTL。
- Redis 不可用时锁降级为进程内锁（现状行为），保证不因 Redis 故障扩大并发风险。

## 四、基础设施设计（阶段 0）

1. **依赖**：`redis>=5.0` 加入 requirements.txt。
2. **配置**（config/config.py）：
   - `REDIS_URL = os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')`
   - `REDIS_KEY_PREFIX = os.getenv('REDIS_KEY_PREFIX', 'ops:platform:')`
   - `REDIS_ENABLED = os.getenv('REDIS_ENABLED', 'true')`（总开关，置 false 即整体回退）
   - 各功能可单独开关（如 `REDIS_AUTH_ENABLED` 等），便于分阶段灰度。
3. **封装**：新建 `core/redis_client.py`，提供：
   - `get_redis()`：懒加载连接池（`redis.from_url`，`decode_responses=True`，`socket_timeout` 短超时）。
   - `safe_*` 包装：所有命令 try/except，Redis 异常返回 None/False 并打日志，**永不抛出到业务**。
   - `cache_get/cache_set/cache_delete`：统一读穿透/失效入口。
   - `acquire_lock/release_lock`：SET NX PX + Lua 释放。
4. **本地部署**：docker-compose.yml 增加可选 `redis` 服务（或复用 K8s 中间件 Redis，见待确认事项）。
5. **验收**：应用启动时 Redis 连通性自检（失败仅告警不阻断）；提供 `GET /health` 增加 redis 状态字段。

## 五、分阶段实施计划

### 阶段 0：基础设施（1 个 PR）
- 依赖、配置、`core/redis_client.py` 封装、docker-compose redis 服务、健康检查。
- 不改任何业务行为；验收 = 启动正常、Redis 挂掉应用仍正常。

### 阶段 1：认证会话 + 登录限流
- `auth_api.login`：写库后写 Redis 会话缓存；`logout` / `change_password` 删除缓存。
- `core/security.validate_token`：先读 Redis（命中直接构造 User 快照），未命中回源 DB 并回填。
- 登录失败计数 + 锁定（INCR + EXPIRE）。
- 验收：重复请求不再打 `auth_tokens` 查询；连续失败 N 次锁定；Redis 挂掉鉴权走 DB 正常。

### 阶段 2：系统设置缓存（已取消）
- 原计划读穿透缓存 + 失效；实际评估设置量小、查询快，**取消设置缓存**，`settings_service` 直连 MySQL。

### 阶段 3：Agent 心跳与调度概览
- `heartbeat_by_name`：心跳写 Redis（含指标 JSON + 时间戳），DB 落库改为节流（如每 30s 或指标变化超过阈值时）。
- `check_offline_agents`：改为优先基于 Redis 心跳时间戳判断，离线再回写 DB。
- `schedule_api._overview`：结果缓存 2s，多 SSE 客户端共享。
- `get_agents_docker_cache`：改为读 Redis 缓存。
- 验收：Agent 心跳不再每 5s 全量扫库；概览页多开不放大 DB 压力；节点离线判定 ≤15s。

### 阶段 4：分布式锁与原子派发
- `dispatch_service`：`dispatch_pending` 全局锁（跨 worker）；pending 队列迁移 ZSET + `claim` 原子领取；替换进程内 `_dispatch_lock`。
- `auto_deploy`：`_env_locks` 替换为 `ops:platform:lock:deploy:{env}`，锁失败则排队/跳过并记录。
- `collation.tasks`：任务注册表迁移 Redis（或至少加任务级锁防重复执行）。
- `agent_service.poll_build_by_name`：领取构建用 `claim:{id}` SETNX 防两个 worker 同时派同一构建。
- 验收：压测多 worker 并发触发，无重复派发/重复部署；锁超时自动释放。

### 阶段 5（可选）：SSE 跨 worker 实时推送 + 构建进度
- 构建状态/步骤变化 publish 到 `ops:platform:sse:event`，各 worker SSE 订阅后推送；保留 5s 轮询兜底。
- `agent_build_step` / `complete_build` 同步更新 Redis 进度/状态。
- 验收：多 worker 下状态变化 <1s 推送到前端；Redis 挂掉自动回到轮询模式。

## 六、风险与注意事项

1. **Redis 必须可降级**：所有读路径缓存未命中/异常回源 DB；所有写路径先保证 DB 成功；锁降级为进程内锁。禁止任何"Redis 挂了业务就挂"的写法。
2. **数据一致性**：缓存一律 Cache-Aside（先更库、再失效/更新缓存）；指标类允许秒级滞后。
3. **敏感数据**：密码/凭据不进 Redis；如后续必须缓存，需加密 + 极短 TTL，并在本表登记。
4. **内存控制**：所有 key 有 TTL；定期 `INFO` 监控；预计数据量（agent 数十个、token 数十~数百、概览 1 个）远小于默认 512MB，无需额外清理任务。
5. **键冲突**：遵循统一前缀，避免与平台其他系统共用 Redis 实例时冲突（多环境建议追加环境段）。

## 七、待确认事项

1. **Redis 部署方式**：A) docker-compose 本地新增 redis 服务（开发/单机） B) 复用 K8s 中间件 Redis（生产） C) 指定外部 Redis 地址 —— 请确认。
2. **键前缀**：单环境默认 `ops:platform:`；是否追加环境段（dev/prod 共用实例时强烈建议追加）。
3. **实施范围**：阶段 1–4 是否都做；阶段 5（SSE 实时推送）是否纳入本期。
4. **敏感字段**：确认设置缓存与实例发现缓存都不包含密码类字段（默认方案如此）。

### 后续变更（2026-08-04）

- **认证改为纯 Redis**：`auth_tokens` 表及模型已删除（MySQL 13 张表），登录会话只存 Redis（db 1）。
- 登录时 Redis 写入失败返回 503 拒绝发 token；鉴权仅查 Redis，Redis 故障时所有请求按未登录处理（无 MySQL 兜底）。
- 已确认接受“Redis 重启后全部用户需重新登录”的风险（不强制开启 RDB/AOF 持久化）。

---

## 八、已确认决策（2026-08-04）

1. **Redis 部署**：使用外部 Redis `192.168.6.2:6380`（需认证，db 1）；本地 docker-compose 不新增 redis 服务。
2. **键前缀**：`ops:platform:`（不追加环境段）。
3. **实施范围**：阶段 1–4 全部执行；阶段 5（SSE 跨 worker 实时推送）本期不做，保留 5s 轮询现状。
4. **敏感字段**：密码/凭据类字段不进 Redis（设置缓存跳过 HIDDEN_FIELDS，实例发现缓存不含密码）。

实施记录：
- [x] 阶段 0 基础设施（依赖/配置/core.redis_client/健康检查）
- [x] 阶段 1 认证会话 + 登录限流（auth_tokens 缓存、用户→token 索引失效、失败锁定）
- [x] 阶段 2 设置缓存（已取消：设置直连 MySQL）
- [x] 阶段 3 Agent 心跳/概览（心跳只写 Redis、MySQL 仅存配置、概览 2s 缓存）
- [x] 阶段 4 分布式锁/原子派发（dispatch/构建领取/自动部署/collation 锁 + 任务状态镜像）
- [x] 真实 Redis 端到端验证（db 1）：登录会话缓存、Agent 心跳/在线判定、
      调度概览缓存、分布式锁、登录限流全部实测通过
