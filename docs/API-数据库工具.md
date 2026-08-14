# API - 数据库工具

> 认证方式与通用响应见 [API文档.md](API文档.md)。

## 1. 实例与数据源

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/database/instances` | 实例列表（自动 + 自定义） |
| GET | `/api/database/databases` | 实例数据库列表 |
| GET | `/api/database/tables/<database>` | 表列表 |
| GET | `/api/database/columns/<database>/<table>` | 字段列表 |
| GET | `/api/database/column_issues/<database>` | 字段问题清单 |
| GET | `/api/database/datasources` | 自定义数据源列表 |
| POST | `/api/database/datasources` | 创建自定义数据源 |
| POST | `/api/database/datasources/<id>` | 更新自定义数据源 |
| DELETE | `/api/database/datasources/<id>` | 删除自定义数据源 |
| POST | `/api/database/datasources/test` | 连接测试 |

## 2. 排序修复任务

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/database/fix_database_async` | 库级异步修复 |
| POST | `/api/database/fix_table_async` | 表级异步修复 |
| POST | `/api/database/fix_all_tables_async` | 一键全表异步修复 |
| POST | `/api/database/fix_columns_async` | 指定字段异步修复 |
| GET | `/api/database/stream?task_key=` | 修复/同步进度 SSE |
| GET | `/api/database/report/<database>` | 校验报告下载 |

## 3. 表结构对比与同步

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/database/compare_structure` | 表结构对比（源库 → 目标库，逐表差异 + 汇总） |
| POST | `/api/database/sync_structure_sql` | 预览同步 SQL（不执行） |
| POST | `/api/database/sync_structure_async` | 异步执行表结构同步 |

## 4. DDL 自动同步 `/api/database/ddl-sync`

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/database/ddl-sync/projects` | 可选项目 |
| GET | `/api/database/ddl-sync/instances` | 可选源实例（含监听状态） |
| GET | `/api/database/ddl-sync/tasks` | 任务列表 |
| POST | `/api/database/ddl-sync/tasks` | 创建任务 |
| PUT | `/api/database/ddl-sync/tasks/<id>` | 更新任务 |
| DELETE | `/api/database/ddl-sync/tasks/<id>` | 删除任务 |
| POST | `/api/database/ddl-sync/tasks/<id>/toggle` | 启用/暂停 |
| GET | `/api/database/ddl-sync/logs` | 日志查询 |
| GET | `/api/database/ddl-sync/logs/stream/<task_id>` | 日志 SSE |
