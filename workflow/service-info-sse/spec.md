# 服务信息卡片 SSE 实时化改造

> 状态：已完成（2026-08-14）。边界见 [scope.md](./scope.md)。

## 任务目标

服务信息卡片四项数据（镜像/端口/副本/Pod）改为 SSE 实时推送，镜像显示 Pod 实际运行镜像，滚动更新时能实时看到容器重启与镜像变化。

## 背景与问题根因

1. **image 不更新**：`list_services` 走 K8s 时读的是 Deployment spec 镜像（spec 已更新但旧 Pod 仍在跑）；K8s 异常时回退读本地 deployment YAML 旧文件，更滞后。真因：`list_deployments` 误用 CoreV1Api 调 `list_namespaced_deployment` 必然报错，K8s 路径全失败回退旧 YAML → 改用 AppsV1Api
2. **决策**：镜像只展示 Pod 实际运行镜像（`container_statuses[].image`），滚动更新期间多镜像去重展示

## 卡片数据源划分（四部分）

| 数据 | 来源 | 加载方式 |
| --- | --- | --- |
| 镜像/副本/Pod 状态/端口 | K8s API | SSE 实时推送 |
| 运行日志 | K8s API | SSE（已有 `pod_log_stream`，未动） |
| Nacos 配置 | Nacos Open API | HTTP 按需加载 |
| 环境变量 | K8s Deployment spec | HTTP 按需（`/service-info/envs`，不随列表/SSE 携带） |

## 涉及文件

| 文件 | 改动 |
| --- | --- |
| `modules/deploy/services/kube_client.py` | AppsV1Api 修复；`_pod_summary` 实际镜像/app 标签；`_watch` 通用生成器（Pod+Deployment 双流）；`build_service_snapshot` |
| `modules/deploy/api/service_info_stream_api.py` | 新增：`/service-info/stream`（快照+watch 增量+30s 心跳+内容去重）、`/service-info/envs` |
| `modules/deploy/api/service_info_api.py` | `list_services` 改用快照构建（镜像=实际运行镜像） |
| `modules/deploy/routes.py` | 注册 SSE/envs 路由 |
| `static/js/modules/deploy/ServiceInfoPage.js` | 卡片主数据源改 SSE（snapshot/update 全量替换，error/连续断连回退 HTTP）；openEnv 改调 envs 接口 |

## 阶段记录（全部完成）

- [x] 阶段一：后端数据基础（实际镜像/app 标签/快照构建）
- [x] 阶段二：SSE 流接口（快照+增量+心跳；K8s 不可用推 error 前端回退）
- [x] 阶段三：前端改造（SSE 订阅、openEnv 改 HTTP、切换环境关旧流、多镜像显示 ×N）
- [x] 阶段四：回归验证（YAML 弹窗/Pod 日志流/Nacos/envs 全正常，回退路径保留）

## 进度与踩坑记录

| 日期 | 进展 | 问题与决策 |
| --- | --- | --- |
| 2026-08-14 | 完成现状分析与规划 | 镜像仅展示 Pod 实际运行镜像；卡片四项走 SSE，envs/Nacos 保持 HTTP |
| 2026-08-14 | 明确四部分数据源划分 | envs 实际来自 K8s API（非本地 YAML，仅回退路径读文件）；envs 弹窗改独立 HTTP 接口实时读 K8s |
| 2026-08-14 | 修复 image 不更新根因 | CoreV1Api 无 `list_namespaced_deployment`，改用 AppsV1Api |
| 2026-08-14 | 阶段二完成 | watch 用 `_watch` 通用生成器（超时自动重建）；实测 snapshot+心跳正常，无变化不推送 |
| 2026-08-14 | 阶段三完成 | 实测 ysh/api 15 卡片 SSE 渲染、镜像=实际运行镜像、环境变量弹窗 39 项正常；踩坑：Vue 模板字面量内 `'\n'` 被 JS 转义成真实换行导致模板编译报错，改 `'\\n'` |
| 2026-08-14 | 阶段四完成 | 回归全正常，任务完成 |
