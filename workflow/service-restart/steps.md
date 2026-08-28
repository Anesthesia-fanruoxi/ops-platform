# 步骤规划：服务信息页「Pod 重启」

> 任务目录：`workflow/service-restart/`
> 关联规则：先在任务目录写 steps.md + boundaries.md + ui.md → 用户确认后开始执行 → 各步骤依次执行不再逐步确认 → 每步完成后验收并标记。
> 当前结论：卡片上的「重启」= 重启该服务（rollout restart Deployment，含内部多 container 一起重建）；页面级「重启全部服务」= 对整个 namespace 下所有 Deployment rollout restart。**复用现有部署权限**，不新增权限码。

## 目标

在服务信息页（`static/js/modules/deploy/ServiceInfoPage.js`）提供两种重启能力：

1. **单服务重启**：每张服务卡片在「环境变量」按钮后追加一个黄色「重启」小按钮，点击 → 二次确认 → `rollout restart` 该服务对应的 Deployment（内部所有 container 一并滚动重建）。
2. **重启全部服务**：工具栏新增「重启全部服务」按钮，点击 → 二次确认（提示影响面）→ 对该 namespace 下所有 Deployment 逐个 `rollout restart`，即整个 namespace 的所有 pod 滚动重建。

两处操作均为有副作用的写操作，成功后通过重建 SSE / 重拉 `/api/deploy/service-info/list` 刷新卡片状态（pod 重建期间短暂 Pending 再回 Running，用于验证效果）。

---

## 步骤拆解

### 步骤 1 · 后端 K8s 能力：rollout restart
- 在 `modules/deploy/services/kube_client.py` 新增：
  - `deployment_namespace(project, env)`：按现有 `build_service_snapshot` 同规则推导 namespace（格式 `{project}-{env}-service`）。
  - `restart_deployment(namespace, name)`：调用 K8s `AppsV1Api.patch_namespaced_deployment`，在 deployment spec.template.metadata.annotations 写入 `kubectl.kubernetes.io/restartedAt=<now UTC RFC3339>`，触发滚动重启（即 `kubectl rollout restart` 等价实现）。
  - `restart_all_deployments(project, env)`：先用 `list_namespaced_deployment` 枚举该 namespace 下所有 Deployment，逐个调用 `restart_deployment`，汇总成功/失败清单返回。
- 容错：Deployment 不存在 → 明确报错；namespace 不存在 / 无权限 → 明确报错。
- 验收：`python -c` 导入正常；用测试环境工具/脚本手测单服务与整 namespace 触发，观察 pod 滚动重建。

### 步骤 2 · 后端接口 + 路由（复用部署权限）
- 在 `modules/deploy/api/service_info_api.py` 新增两个接口（用 `@require_permission('op:deploy')` 或现有部署相关权限码，执行时确认 `canDeploy` 对应码）：
  - `POST /api/deploy/service-info/restart` → body `{ project, env, service_name }`；调 `restart_deployment`，成功 `success_response`，失败 `error_response(msg, status_code)`；记录审计日志。
  - `POST /api/deploy/service-info/restart-all` → body `{ project, env }`；调 `restart_all_deployments`，返回成功/失败清单；记录审计日志。
- 在 `modules/deploy/routes.py` 用 `add_url_rule` 注册上述两条路由（methods=['POST']）。
- 权限复用：不新增权限码，沿用服务信息页现有部署操作权限（与「快捷部署」按钮同源）。
- 验收：curl/Postman 用带 token 请求验证；无权限用户 403；单服务与重启全部均触发成功；失败场景（service 不存在）报错明确。

### 步骤 3 · 前端口语化：卡片「重启」按钮（黄色）
- 在 `.svc-card-actions` 的「环境变量」按钮**之后**追加：
  ```html
  <el-button link type="warning" size="small" :loading="restarting[svc.name]" @click="restartService(svc)">重启</el-button>
  ```
- `data` 新增 `restarting: {}`（按 `svc.name` 记录 loading 态）。
- `restartService(svc)`：
  1. `ElMessageBox.confirm('确定重启服务「' + svc.name + '」吗？其内部 Pod 会滚动重建，期间可能短暂不可用。', '重启服务', { type:'warning', confirmButtonText:'确定重启', cancelButtonText:'取消' })`；
  2. 确认后置 `restarting[svc.name]=true`，调 `ajax('POST','/api/deploy/service-info/restart',{project,env,service_name:svc.name}, cb)`；
  3. 成功 → `ElMessage.success('已触发 ' + svc.name + ' 重启')`；失败 → `ElMessage.error(res.msg)`；
  4. `finally` 清 loading，并触发刷新（重建 SSE 或重拉 list）以展示 pod 重建过程。
- 验收：卡片「环境变量」后出现黄色「重启」按钮；点击弹确认；取消不触发；确认后 loading、成功提示、卡片状态随后刷新体现重建。

### 步骤 4 · 前端页面级「重启全部服务」按钮
- 在工具栏（「快捷部署」旁）新增：
  ```html
  <el-button v-if="selectedProject && selectedEnv" type="danger" plain size="small" :loading="restartingAll" @click="restartAllServices">⟳ 重启全部服务</el-button>
  ```
- `data` 新增 `restartingAll: false`。
- `restartAllServices()`：
  1. `ElMessageBox.confirm('将对该命名空间下所有服务（所有 Pod）执行滚动重启，全部服务会短暂不可用，确定继续？', '重启全部服务', { type:'warning', confirmButtonText:'确定重启全部', cancelButtonText:'取消' })`；
  2. 确认后置 `restartingAll=true`，调 `ajax('POST','/api/deploy/service-info/restart-all',{project,env}, cb)`；
  3. 成功 → `ElMessage.success` 汇总结果（含个别失败服务清单）`ElMessage.warning`；失败 → `ElMessage.error`；
  4. `finally` 清 loading 并刷新；该按钮 `v-show`/位置需与项目工具栏现有 `v-if` 风格保持一致。
- 验收：选齐项目/环境后按钮可用；点击弹强提示确认；触发后 loading；成功后整体刷新，观察所有 pod 滚动重建。

### 步骤 5 · 边界、健壮性、验收与回归
- 二次确认覆盖所有写操作；loading 防重复点击；接口失败保留现有页面状态不白屏。
- SSA 刷新用现有一致机制（`watch_pods` 重建 或 `loadServices`），避免卡片状态与真实 pod 阶段漂移。
- `node --check` 通过；Python 端接口/导入正常（`python -c` import）。
- 手动验证：单服务重启 → 滚动重建 → 状态恢复；重启全部服务 → 全 namespace 滚动 → 恢复；无权限 403；svc 不存在报错明确。
- 回归：原有服务卡片 SSE、日志、日志目录、Nacos、环境变量、快捷部署、收藏栏**全部不受影响**。
- 踩坑与决策记入本文件「进度记录」。
- 验收后立即更新 `workflow.md` 将对应步骤标记 [x]。

---

## 进度记录

| 步骤 | 状态 | 备注 |
|------|------|------|
| 1 后端 K8s rollout restart | 已完成（待测试环境手测） | 新增 deployment_namespace / restart_deployment / restart_all_deployments；patch 写 kubectl.kubernetes.io/restartedAt 注解 |
| 2 后端接口 + 路由 | 已完成（待测试环境手测） | restart / restart-all，@require_permission('op:cicd_build')，审计由全局拦截器自动落库 |
| 3 卡片「重启」按钮 | 已完成（待测试环境手测） | 黄色、环境变量后、确认+loading+刷新 |
| 4 页面级「重启全部服务」 | 已完成（待测试环境手测） | 工具栏、危险色、强确认 |
| 5 验收与回归 | 进行中 | node --check + 接口手测 + 回归（运行态需在测试 namespace 验证） |

## 关键决策与踩坑

- **权限选型**：steps.md 写「复用部署权限（与快捷部署同源）」。实际前端 `canDeploy` = `$auth.hasPermission('op:cicd_build')`（见 ServiceInfoPage.js:697-699），故后端两个接口统一用 `@require_permission('op:cicd_build')`、前端两个按钮均 `v-if="... && canDeploy"`，与「快捷部署」按钮完全同源。
- **审计日志**：未显式调用 `record_audit`，依赖 `core/audit.py` 的全局 after_request 拦截器——所有 POST 写操作自动落库（module=service_info、action=restart/restart-all），与现有接口一致，无需手动注入。
- **rollout restart 实现**：采用 `patch_namespaced_deployment`（content_type=application/merge-patch+json）在 `spec.template.metadata.annotations` 写入 `kubectl.kubernetes.io/restartedAt=<now UTC RFC3339>`，等价 `kubectl rollout restart`，不 delete pod（滚动优雅）；merge patch 保证与原 annotations 合并而非覆盖。容错：404→Deployment 不存在、401/403→无权限，均转 KubeNotConfigured 透传明确报错。
- **namespace 推导**：复用 `list_services` 同规则 `f'{project}-{env}-service'`，新增 `deployment_namespace()` 统一收口。
- **前端刷新**：重启成功后调 `loadServices()` 重建 SSE 快照，卡片 pod 状态（Pending→Running）随之体现重建过程；`restarting` 用 `$set/$delete` 按 svc.name 维护 loading 态，避免互相影响。
- **语法校验**：Python `py_compile` 三文件通过；前端 `node --check` 通过。运行态手测（真实 rollout restart、403、svc 不存在报错）需在测试 namespace 执行。