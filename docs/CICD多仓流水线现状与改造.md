# 多仓库 CI/CD 现状与改造记录

更新时间：2026-11-26

## 1. 结论

多仓库的“配置层”和“单仓执行层”已经适配；但**还不是一条真正的一键多仓流水线**。

当前能做的：

- 一个项目配置一份多仓库模板。
- 模板下配置 19 个仓库、44 个服务。
- 每个仓库独立选择 Git 凭据、Git 镜像、编译镜像、编译命令、Dockerfile。
- 每个服务配置产物目录、精确 jar 名、Java 版本。
- 单个仓库可以触发构建，生成一个 Build 记录。
- Agent 按单个仓库任务 clone、编译、收集 jar、构建镜像、推送。
- 构建成功后自动部署会识别 `build_mode=multi`，按该仓库的服务列表修改 YAML tag 并 apply。

当前不能做的：

- 没有一个“构建全部仓库/全部服务”的入口。
- 19 个仓库要逐个点击构建。
- 环境页、服务信息页的快捷构建没有走多仓库模板。
- 没有跨仓库批次状态、失败聚合、全量成功后再统一部署。
- 没有和 Apollo/Middleware/环境创建串成一条流水线。

## 2. 已实现链路

### 2.1 多仓库模板

- 模型：`CicdMultiTemplate` → `CicdMultiItem` → `CicdMultiService`。
- 服务名同时作为镜像名、K8s Service/Deployment 名。
- 仓库名从 Git URL 最后一段自动推导。
- 服务映射的 `artifact_dir` 和 `jar_name` 精确到文件。
- 导入 JSON：`config/multi-repo-template.verified.json`（19 仓 / 44 服务）。

### 2.2 单仓构建

入口：

```text
POST /api/cicd/multi-templates/items/<item_id>/build
```

实际执行：

```text
trigger_item_build
  -> 查 item / environment / Maven Settings
  -> 生成 services 映射
  -> 可选追加 maven-deploy-plugin 发布命令
  -> 创建 Build(steps_snapshot.build_mode=multi)
  -> dispatch_pending
```

Agent 侧仍是单仓库任务：

```text
clone 一个 Git URL
-> 执行一个 build_command
-> 按 artifact_dirs/jar_name 收集产物
-> 逐服务构建 Docker 镜像
-> 推送 Harbor
```

因此多仓库适配的是“多行配置 + 每次执行一个仓库”，不是“一个 Agent 任务同时 clone 19 个仓库”。

### 2.3 自动部署

`auto_deploy.py` 已处理：

- `steps_snapshot.build_mode == 'multi'`
- 从 snapshot.services 取出该仓库本次产出的服务名
- 按服务逐个修改远程 YAML 的镜像 tag
- 只 apply 涉及的服务 YAML，不触碰同环境其他仓库的服务

这部分是可复用的。

## 3. 关键缺口

### 3.1 没有构建全部仓库

前端多仓库弹窗明确写着：

```text
只构建这一个仓库
```

对应接口也只有：

```text
POST /api/cicd/multi-templates/items/<item_id>/build
```

没有：

```text
POST /api/cicd/multi-templates/<template_id>/build
```

或 batch/all 入口。

### 3.2 环境页快捷构建未适配多仓

`ManagePage.executeBuild` 和 `mixin-quickbuild.executeBuild` 调用的仍是：

```text
POST /api/cicd/builds/trigger
```

只传 `project_id/environment_id/branch/services/project_type`，没有 `multi_item_id`。

结果：

- 多仓项目在环境页点“构建”时，后端按单仓模板找 `CicdFlowTemplate`。
- 没有单仓模板时会报“该项目未配置 CI/CD 流程模板”。
- 即使能触发，也不会走多仓模板。

### 3.3 `/builds/trigger` 的多仓分支丢失 Maven Settings 覆盖

`build_service.trigger_build` 的多仓分支调用：

```python
return trigger_item_build(multi_item_id, environment_id, branch, triggered_by)
```

没有把调用参数里的 `maven_settings_id` 传下去。单独的多仓 item 接口是传了的，但通用 trigger 接口将来用于环境页时会有缺口。

### 3.4 没有批次/聚合状态

当前每个仓库生成一个独立 Build：

- 没有 parent/batch id。
- 无法在 UI 显示“19 个仓库 14 成功 5 失败”。
- 无法在所有仓库成功后统一做一次部署校验。
- 自动部署仍按单个构建触发，可能出现部分仓库先部署、部分仓库还没构建完。

### 3.5 没有环境创建流水线联动

当前“一键扩展环境”在文档中还是手工步骤：

- 创建 namespace
- 部署中间件
- 初始化数据库
- Apollo 环境/Meta
- java-option
- 构建并推送镜像
- apply Service/Deployment

CICD 只负责其中一个构建环节，还没有和环境编排状态机对接。

## 4. 建议改造

### 4.1 增加批次模型

建议新增 `CicdBuildBatch`：

```text
id, batch_no, project_id, environment_id, template_id,
branch, status, total, success, failed, running,
created_by, started_at, finished_at
```

每个子 Build 增加：

```text
batch_id
```

### 4.2 增加构建全部/选中仓库接口

```text
POST /api/cicd/multi-templates/<template_id>/build-batch
{
  environment_id,
  branch 或 items:[{item_id, branch}],
  item_ids,
  maven_settings_id,
  auto_deploy
}
```

后端遍历 item，创建多个 Build，挂同一个 batch_id；受 Agent 并发容量控制。

### 4.3 支持每个仓库不同分支

多仓模板通常不同仓库分支不同。批次参数建议支持：

```json
{
  "items": [
    {"item_id": 1, "branch": "master"},
    {"item_id": 2, "branch": "develop"}
  ]
}
```

### 4.4 环境页快捷构建分流

环境页先查项目是否存在多仓库模板：

- 存在：打开多仓构建弹窗，选择仓库/服务/分支，调用 batch 接口。
- 不存在：继续走现有单仓 `/builds/trigger`。

### 4.5 聚合状态和部署门禁

批次状态机建议：

```text
pending -> running -> build_success -> deploying -> success
                         -> failed
```

- 构建全部成功后再统一 apply Deployment。
- 任一失败可选择“继续已成功部分”或“整批终止”。
- 部署后等待 readiness，再标记批次完成。

### 4.6 与环境一键化状态机合并

后续把 batch 作为环境状态机的一步：

```text
middleware_ready
-> db/apollo_ready
-> build_batch
-> deploy_services
-> readiness_check
-> notify
```

这样才是真正的“一键扩展环境 + 自动化流水线部署”。

## 5. 现在可以直接怎么用

当前可用的多仓路径：

1. 在 CICD 配置页导入 `config/multi-repo-template.verified.json`。
2. 按仓库逐行选择 Git 凭据、Java 8/17 Dockerfile、Maven Settings。
3. 对每个仓库点“构建”，选择环境和分支。
4. 每个仓库成功后自动部署该仓库对应服务。

如果目标是 44 个镜像一次全部产出，当前仍需逐个仓库触发；本次已经手工构建并推送了 44 个镜像，可作为过渡。

## 6. 2026-11-26 已实现的分支规则

多仓表格已支持勾选多个仓库：

- 只勾选一个仓库：使用该仓库自己的分支，可选择。
- 勾选多个仓库：统一使用**第一个选中仓库**的分支，其他仓库不再单独选择分支。
- 新增接口：

```text
POST /api/cicd/multi-templates/<template_id>/build-batch
{
  environment_id,
  item_ids: [...],
  branch: "第一个仓库的分支",
  maven_settings_id
}
```

- 后端先校验全部仓库，再批量创建 Build，最后一次触发 dispatch。
- 每个 Build 仍按仓库独立执行，自动部署按仓库服务列表执行。

仍待补：

- 批次聚合状态（成功/失败/运行中总数）。
- 环境页/服务信息页快捷构建接入多仓 batch。
- 所有仓库成功后统一部署门禁。

## 7. 2026-11-26 服务优先构建交互

环境信息页和服务信息页的构建弹窗已按服务选择改造：

- 单仓库/单服务：保持左侧分支、右侧服务；选择该仓库自己的分支。
- 多仓库：左侧服务、右侧分支。
- 第一次选中某个服务时，才查询该服务所属仓库的分支；后续继续选服务不再查询，统一沿用第一个服务的分支。
- 全部取消后清空分支；下一次重新选中第一个服务时重新查询分支。
- 提交时按选中服务去重到仓库，调用：

```text
POST /api/cicd/multi-templates/<template_id>/build-batch
{ environment_id, item_ids, services, branch, maven_settings_id }
```

只构建选中的服务；未选择服务的仓库不产生 Build。

注意：当前数据库里的多仓模板 `id=2` 绑定在 `project_id=14`，而 goshop 项目是 `project_id=15`；环境页按项目查模板会查不到，需要把模板重新保存/导入到 goshop 项目后再验证。
