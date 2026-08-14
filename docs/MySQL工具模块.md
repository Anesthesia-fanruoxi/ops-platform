# MySQL 工具模块（排序修正 + 表结构对比同步 + DDL 同步）

> 覆盖：MySQL 实例发现、排序规则校验、异步修复（库/表/字段）、表结构对比与同步、binlog DDL 自动同步、SSE 实时日志

## 功能概览

| 子功能 | 说明 |
|---|---|
| 实例发现 | 自动发现（部署环境含 mysql 中间件）+ 自定义数据源 |
| 排序校验 | 检测库/表/字段排序规则与目标 `utf8mb4_0900_ai_ci` 的差异 |
| 异步修复 | 库级 / 表级 / 字段级修复，后台线程执行 |
| 结构对比 | 源库 → 目标库 单向对比表/字段/索引/表选项差异 |
| 结构同步 | 缺表建表、字段增改、索引增改、表选项修改，异步执行 |
| DDL 同步 | 监听源库 binlog，自动转发 CREATE/ALTER/RENAME 到目标源 |
| 进度推送 | 单一日志文件 + SSE 实时 tail |

## 实例发现

- **自动**：遍历 `environments.deploy_config` 中含 mysql 中间件的环境；连接端口优先读 `product/{项目}-{环境}/middleware/mysql.yaml` 的 nodePort，回退 `middleware_port + 下标`。
- **自定义**：用户录入 `collation_datasources`（host/port/user/password）。
- 实例 ID 规则：自动 = `env.id`（数字），自定义 = `custom-{id}`。
- 发现结果缓存 Redis（`cache:database:instances`，TTL 60s）。

## 排序修复方式

| 级别 | 操作 |
|---|---|
| 库 | `ALTER DATABASE ... CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci` |
| 表 | `ALTER TABLE ... CONVERT TO CHARACTER SET ...` |
| 字段 | 逐字段 `ALTER TABLE ... MODIFY` |

- 超过 `MAX_ROWS_THRESHOLD`（默认 10 万行）的表默认跳过，需显式确认。
- 同实例并发修复用 Redis 锁（`lock:database:{instance_id}`）串行，任务状态镜像 Redis 供跨 worker SSE 读取。

## 表结构对比与同步

### 对比维度（源库 → 目标库 单向）

| 对象 | 处理方式 |
|---|---|
| 目标缺失表 | 按源库元数据重建 `CREATE TABLE`（含引擎/排序规则/注释/索引） |
| 字段缺失 | `ADD COLUMN`，按源库字段顺序自动 `AFTER` 定位 |
| 字段定义不一致 | `MODIFY COLUMN`（类型/字符集/排序/可空/默认值/扩展/注释任一不同即视为差异） |
| 索引缺失/不一致 | `ADD KEY` / `DROP INDEX + ADD KEY`；主键差异与全文/空间索引仅提示不生成 SQL |
| 表选项差异 | `ALTER TABLE` 修改引擎/排序规则/注释 |
| 视图缺失/定义不一致 | `CREATE VIEW` / `CREATE OR REPLACE VIEW`（不携带 DEFINER，定义不可读时不判差异） |
| 事件缺失/定义不一致 | `CREATE EVENT` / `DROP EVENT IF EXISTS + CREATE EVENT`（对比事件体/调度/状态/注释） |
| 目标多余表/字段/索引/视图/事件 | **仅提示不删除**（安全约定） |

前端差异按「新建 / 修改 / 删除」三类归组展示，每行附对象类型标签（表/视图/事件）。

### 执行方式

- 对比与 SQL 预览为同步接口；实际执行走后台线程（同修复任务的 SSE 日志模式）。
- 同步前在任务内重新对比一次，保证执行的 DDL 基于最新结构。
- 每条 SQL 独立提交，单表失败记 ERROR 并跳过该表后续 SQL，不阻断其余表。
- 目标实例并发锁复用 `lock:database:{instance_id}`，与排序修复互斥。
- 权限码：查看/对比 `page:database`，执行同步 `op:structure_sync`。

## DDL 自动同步（binlog 监听）

`modules/database/ddl_sync.py` 实现 DdlSyncManager，进程内管理「任务 × 数据源」监听线程，配置变化自动增量对齐。

### 监听与位点

- 用 `mysql-replication` 的 `BinLogStreamReader` 只监听 `QUERY_EVENT`，同步所有库并自动跳过系统库。
- 首次从当前位点开始（存量差异不动），之后从任务记录位点恢复，每 30s 回写位点。
- 每个源上的多个任务监听使用互不相同的派生 `server_id`。

### 多 worker 防重

- 每个监听启动前先抢 Redis 锁 `lock:ddl_sync:{task_id}:{instance_id}`（TTL 60s，监听线程每 20s 续约）。
- Redis 不可用时不启动监听（宁可不同步，避免多 worker 重复执行）。

### 分发规则

| DDL 动词 | 处理 |
|---|---|
| CREATE / ALTER / RENAME | 转发原始 SQL 到其他勾选源（排除变更源与忽略同步源） |
| DROP / TRUNCATE | 不执行，仅记 `skipped` 日志提示 |

### 配置生效

- 常驻协调线程每 15s `reload()`，与 DB 任务配置增量对齐：新任务起线程、删除/暂停/移除源停线程。
- 权限码：查看 `page:ddl_sync`，增删改 `op:ddl_sync`。

## 核心表

| 表 | 说明 |
|---|---|
| `collation_datasources` | 自定义 MySQL 数据源（name/host/port/user/password） |
| `ddl_sync_tasks` | DDL 同步任务（源/目标源、过滤规则、启用状态、binlog 位点） |
| `ddl_sync_logs` | DDL 同步执行日志（转发/skipped/位点回写） |

## 主要接口

- `/api/database/instances`：实例列表（自动 + 自定义）
- `/api/database/check`：排序规则校验
- `/api/database/fix-*`：异步修复任务（库/表/一键全表/指定字段）
- `/api/database/compare_structure`（POST）：表结构对比，逐表差异 + 汇总
- `/api/database/sync_structure_sql`（POST）：预览同步 SQL（不执行）
- `/api/database/sync_structure_async`（POST）：异步执行同步，返回 task_key，进度走 `/api/database/stream`
- `/api/database/stream?task_key=`：修复/同步进度 SSE
- DDL 同步：
  - `GET /api/database/ddl-sync/projects`：可选项目
  - `GET /api/database/ddl-sync/instances`：可选源实例（含监听状态）
  - `GET/POST /api/database/ddl-sync/tasks`：任务列表 / 创建
  - `PUT/DELETE /api/database/ddl-sync/tasks/<id>`：更新 / 删除
  - `POST /api/database/ddl-sync/tasks/<id>/toggle`：启用 / 暂停
  - `GET /api/database/ddl-sync/logs`：日志查询
  - `GET /api/database/ddl-sync/logs/stream/<task_id>`：日志 SSE

## 关键文件

- `modules/database/service.py`（发现/校验核心）、`schema_diff.py`（结构对比与 DDL 生成）、`tasks.py`（后台任务）、`ddl_sync.py`（binlog 监听与分发）、`api.py`（接口）
- `static/js/modules/database/`：SchemaComparePage.js（结构对比同步）、DdlSyncPage.js（DDL 同步）、CollationPage.js / DatasourcesPage.js（排序修正）
- `logs/database/database.log`（单一日志文件）
