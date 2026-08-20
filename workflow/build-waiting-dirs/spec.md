# 构建自填充服务目录（部署步骤等待勾选回填模板后重建）

> 状态：代码改造完成（v2 方案，静态验证通过），实测回归待部署。边界见 [scope.md](./scope.md)。通用规则见 [../workflow.md](../workflow.md)。

## 任务目标

后端模板服务目录（`artifact_dirs`）留空时，构建 clone+编译成功后**跳过产物收集/打镜像/推送并正常结束**，等待点放在**部署步骤**（waiting）：平台展示「配置服务目录」按钮，浏览该构建在 Agent 上编译后的 code 目录勾选服务目录，**覆盖回填模板**，然后用户**重新触发构建**走完整流程。替代「跑通编译 → 人肉上服务器看目录 → 手抄回模板」的流程。

## 方案演进（重要）

v1（已废弃）：编译后构建挂起（waiting）→ 勾选回填 → 复用重跑机制从产物收集续跑。
废弃原因：构建任务参数由 `push_task` **一次性下发** Agent，挂起-续跑链路复杂且语义脆弱。
v2（当前）：不挂起、不续跑。编译后跳过收集/打镜像报 success，**部署步骤 waiting** 等勾选回填模板，用户手动重建。链路简单，全部复用既有机制。

## 方案设计

### 流程链路

```
触发构建（模板 artifact_dirs 为空）
  → Agent: clone → 编译成功 → Step3 发现 ArtifactDirs 为空
  → sendStep(3/4/5, skipped) + sendResult(success) 结束任务
  → Master: build.status=success；步骤条显示 3~5 跳过
  → auto_deploy: 后端且无服务目录 → update_deploy_step(waiting) 不执行部署
  → 前端：部署步骤 waiting（process/橙色）+「配置服务目录」按钮
  → 弹窗浏览 code 目录（/list 单层懒加载）→ 勾选 → 保存配置
  → Master: POST /configure-dirs 校验后覆盖回填模板 artifact_dirs（仅模板）
  → 用户重新触发构建 → 完整流程（收集/打镜像/推送/部署）
```

### 状态语义

| 项 | 处理 |
| --- | --- |
| build.status | 不再引入 waiting 构建态；空服务目录构建正常 success |
| build.json 步骤 | 新增 `skipped`（Agent 主动上报）：跳过步骤中性处理，全 success/skipped = 构建 success |
| 部署步骤（key=deploy） | 新增 `waiting` 取值：后端无服务目录时由 auto_deploy 置入，带提示 error |
| 同环境锁 | 正常 success 终态释放（与既有链路一致，无等待占位） |
| 续跑/超时/取消扩展 | 全部移除（v1 遗留：mark_build_waiting / continue_build / fail_expired_waiting_builds） |

### 关键实现点

1. **Agent `build.go`**：Step3 块开头判断 `backend 且 len(ArtifactDirs)==0` → 日志提示 → `sendStep(3,"collect","skipped")`、`sendStep(4,"docker_build","skipped")`、`sendStep(5,"docker_push","skipped")` → `sendResult(buildID,"success","","")` → return
2. **agent_comm_api.py**：step 回调白名单 `running/success/failed/skipped`；result 回调仅 `success/failed`（移除 waiting）
3. **build_service.py**：
   - `update_step_status` 支持 `skipped`（Agent 上报）；总状态：failed > 全 success/skipped=success > running > pending
   - `update_deploy_step` 支持 `waiting`（记 started_at + error 提示）
   - `configure_artifact_dirs(build_id, dirs)`：校验列表非空/路径合法（禁绝对路径与 `..`）→ 覆盖回填模板 `configs.backend.artifact_dirs`（`\n` 拼接，无模板报 400）→ 不动构建状态
   - `cancel_build` 回退为仅 pending 直接取消
4. **auto_deploy.py**：`auto_deploy_build` 中 `backend 且 all_names 为空` → `update_deploy_step(waiting, '未配置服务目录，请配置后重新构建')` 后返回（不部署）
5. **build_api.py / routes.py**：
   - `GET /builds/<id>/code-dirs?path=`（`op:agent_dir`）：去掉 waiting 限制，仅要求绑定在线节点
   - `POST /builds/<id>/configure-dirs`（`op:cicd_build`）：替换原 `/continue`，仅回填模板
6. **template_api.py**：create/update 保持「后端服务目录可留空」（注释更新为 v2 语义）
7. **前端（两构建面板同步）**：
   - 「配置服务目录」按钮：显示条件 = 部署步骤 waiting（`bpDeployWaiting` 计算属性）
   - 弹窗：浏览编译后 code 目录勾选（完整相对路径）→ 保存配置 → 提示「请重新触发构建」
   - 构建弹窗服务范围：加载完成且为空时显示「暂未配置服务」（新增 `servicesLoaded` 标志），不再一直显示「加载服务中...」
   - 移除 waiting 构建态映射；取消按钮条件去掉 waiting
   - CicdConfigPage：服务目录留空提示更新为 v2 语义

## 涉及文件

| 文件 | 改动 |
| --- | --- |
| `agent/build.go` | Step3 空服务目录跳过 3~5 步报 success |
| `modules/cicd/services/build_service.py` | skipped/waiting 步骤支持 + configure_artifact_dirs；删 waiting 三件套 |
| `modules/cicd/services/auto_deploy.py` | 后端无服务目录时部署步骤置 waiting |
| `modules/cicd/services/dispatch_service.py` | 移除 waiting 超时扫描调用 |
| `modules/cicd/api/agent_comm_api.py` | 回调白名单调整（step+skipped，result 去 waiting） |
| `modules/cicd/api/build_api.py` | code-dirs 放开；continue → configure-dirs |
| `modules/cicd/api/template_api.py` | 注释语义更新 |
| `modules/cicd/routes.py` | `/continue` 路由改为 `/configure-dirs` |
| `static/js/modules/deploy/ServiceInfoPage.js`、`ManagePage.js` | 部署等待按钮/弹窗/空态/状态映射（两处同步） |
| `static/js/modules/cicd/CicdConfigPage.js` | 留空提示文案更新 |

## 阶段规划

- [x] 阶段一（v2）：Agent 跳过上报——build.go 空服务目录 → skipped×3 + success；`go build` 通过 ✅
- [x] 阶段二（v2）：Master 状态机——skipped 步骤支持 / 部署步骤 waiting / configure_artifact_dirs / auto_deploy 接入；删除 v1 挂起三件套；PY 语法通过 ✅
- [x] 阶段三（v2）：接口——code-dirs 放开限制、`/configure-dirs` 路由替换 `/continue` ✅
- [x] 阶段四（v2）：前端——部署等待按钮 + 弹窗回填 + 「暂未配置服务」空态 + 状态映射清理（两页面同步）；JS 语法通过 ✅
- [ ] 阶段五：交叉编译 linux/amd64 部署测试节点（保留旧二进制）+ 实测回归

## 检查点与回滚

| 检查点 | 判定标准 | 未通过时的处理 |
| --- | --- | --- |
| 阶段一 | go build 通过 | 单文件改动，直接回滚 |
| 阶段二 | skipped 中性语义、部署 waiting 自洽 | 均独立分支，不影响既有 success/failed 链路 |
| 阶段三 | 接口可用、权限生效 | 新路由独立 |
| 阶段四 | 弹窗可用、空态正确 | 前端独立 |
| 阶段五 | 实测全过 | 保留旧 agent 二进制，可快速回退 |

## 验收标准

- [ ] 模板服务目录留空可保存；触发后端构建，clone/编译成功后 Step3~5 显示跳过，构建状态 success
- [ ] 部署步骤显示 waiting（等待配置），SSE 实时刷新；不执行任何部署动作
- [ ] 构建弹窗「构建范围」在服务目录未配置时显示「暂未配置服务」（不再卡在加载服务中）
- [ ] 点「配置服务目录」弹窗浏览该构建编译后 code 目录（仅工作目录内，越界拒绝），勾选保存后模板 `artifact_dirs` 被覆盖回填
- [ ] 重新触发构建：完整跑通收集/打镜像/推送/部署
- [ ] 已填服务目录的构建全流程行为不变（回归）

## 进度记录

| 日期 | 进展 | 问题与决策 |
| --- | --- | --- |
| 2026-08-19 | v1 阶段一~四完成 | 磁盘挂起+续跑方案落地（详见历史 git） |
| 2026-08-19 | 用户修正为 v2 方案并全量改造 | 任务参数一次性下发 Agent，续跑链路不成立；改为「跳过收集报 success → 部署步骤 waiting → 勾选回填模板 → 手动重建」。删除 waiting 构建态/续跑/超时扫描；新增 skipped 步骤态与部署 waiting；前端空态「暂未配置服务」。静态验证：go build / PY_SYNTAX_OK / JS_SYNTAX_OK 全过 |
