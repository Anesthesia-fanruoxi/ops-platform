# 范围边界：服务信息卡片 SSE 实时化

## 目标内（In Scope）

1. 卡片四项数据 SSE 实时化：镜像、端口、副本数、Pod 状态
2. 镜像字段改为展示 Pod 实际运行镜像（`container_statuses[].image`）
3. 新增 `/api/deploy/service-info/stream` SSE 接口（快照 + 增量 + 心跳，不含 envs）
4. 新增 `/api/deploy/service-info/envs` HTTP 接口，环境变量弹窗打开时实时读 K8s Deployment spec
5. 前端 `ServiceInfoPage.js` 卡片数据源切换为 SSE，HTTP 接口保留作回退

## 目标外（Out of Scope）

1. Nacos 配置查看/编辑 —— 保持 HTTP 按需加载，不动
2. Pod 运行日志 SSE 流（`pod_log_stream`）—— 已存在且正常，不重构
3. 构建状态 SSE（顶部"构建中"提示）—— 不动
4. deployment YAML 旧文件回退逻辑的重写 —— 仅保留为 K8s 不可用兜底

## 涉及对象

| 类型 | 名称/路径 | 说明 |
| --- | --- | --- |
| 文件/模块 | `modules/deploy/services/kube_client.py`、`modules/deploy/api/service_info_api.py`、`modules/deploy/api/service_info_stream_api.py`、`modules/deploy/routes.py`、`static/js/modules/deploy/ServiceInfoPage.js` | 仅允许修改这些文件 |
| 环境 | K8s 测试环境 namespace | 只读操作（list/watch），禁止任何 apply/delete/scale |
| 数据 | 无数据库改动 | 不涉及表结构变更 |

## 变更记录

| 日期 | 变更内容 | 原因 |
| --- | --- | --- |
| 2026-08-14 | 初始范围确定 | 镜像仅展示实际运行镜像；卡片四项走 SSE，envs/Nacos 走 HTTP |
| 2026-08-14 | envs 来源调整 | envs 弹窗改独立 HTTP 接口实时读 K8s，不再随列表/SSE 携带 |
