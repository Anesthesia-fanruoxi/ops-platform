# 边界与红线：服务信息页「Pod 重启」

> 本文件界定本次任务的 scope 内外、约束与红线。超出边界时暂停并询问，不得自行扩展。

## 一、范围（In Scope）

**后端 + 前端联动**（纯功能增强，不涉及数据库新增表）：

1. **后端 K8s 能力**：`modules/deploy/services/kube_client.py` 新增 rollout restart 相关方法。
2. **后端接口**：`modules/deploy/api/service_info_api.py` + `routes.py` 新增 `restart` / `restart-all` 两个 POST 接口。
3. **前端**：`static/js/modules/deploy/ServiceInfoPage.js` + deploy 模块样式文件
   - 每张服务卡片「环境变量」后追加**黄色「重启」按钮**（重启该服务 Deployment，内部多 container 一起重建）；
   - 工具栏新增**「重启全部服务」按钮**（对整个 namespace 下所有 Deployment rollout restart）；
   - 两处均带二次确认、loading 防重复、成功后刷新。

## 二、明确不做（Out of Scope）

- **不做逐 Pod 独立重启**。测试环境单卡片通常只有一个 pod，且复用服务卡片即可表达；本次「重启」= 重启整个服务（Deployment），不细分到单个 pod/container 粒度。
- **不新增权限码**：复用现有部署权限（与「快捷部署」按钮同源），不新增 DB 表 / 权限种子。
- **不动**范围外的模块：CICD 配置页（`CicdConfigPage.js`）、调度中心（`SchedulePage.js`）、Agent、Nacos/Harbor 库存逻辑。
- **不做**重启调度 / 定时重启 / 重启历史台账 / 混部驱逐等高级能力。
- **不引入**新第三方依赖 / 图标库；沿用 Element Plus + 现有 `ajax` 模式 + emoji/内联 SVG。

## 三、技术约束

- 前端模板标签沿用项目约定 `[[ ]]`（非默认 `{{ }}`）。
- 改动后 JS 必须通过 `node --check` 语法校验；Python 改动需 `python -c` 导入验证。
- 调用 K8s rollout restart 采用 `patch_namespaced_deployment` 写 `kubectl.kubernetes.io/restartedAt` 注解的方式（等价 `kubectl rollout restart`），不直接 delete pod（保持缩放/滚动优雅）。
- 接口返回结构遵循项目现有约定 `{code, msg, data}`；写操作记录审计日志。
- 服务卡片/工具栏按钮沿用 Element Plus `link`/`plain` 按钮样式；警示用 `warning`（黄）、批量危险操作用 `danger`（红）。

## 四、红线（必须遵守）

1. **不动生产环境**；不提交密钥 / 凭据；不未经确认删除文件或重置数据。
2. 不改 scope 目标外的模块与接口。
3. **所有重启写操作必须二次确认**：单服务用 warning 确认；「重启全部服务」用醒目危险提示，明确告知整个 namespace 短暂不可用，避免误触发。
4. 接口必须带权限校验，无权限一律 403；失败（service 不存在 / namespace 不存在）报错明确，不静默吞掉。
5. 任何超出上述边界的需求（逐 pod 重启、权限码、定时重启）须暂停并提问，不得擅自实现。

## 五、假设（如与预期不符请指出）

- 「重启」= rollout restart Deployment，含内部多 container 一起滚动重建；非 delete-and-recreate 单个 pod。
- 「重启全部服务」作用范围 = 当前选中 `项目 + 环境` 对应的整个 namespace 下所有 Deployment（pod）。
- 权限 = 复用现有部署权限（无需用户可见变化）。
- 按钮颜色：单服务「重启」为**黄色**（`type="warning"`，符合用户要求）；「重启全部服务」为**红色危险色**（`type="danger"`）。