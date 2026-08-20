# 长任务工作流

> 通用规则在上，任务列表在下；每个任务的详细规划见各自目录的 `steps.md`（步骤）/ `boundaries.md`（边界）/ `ui.md`（UI 设计）。
> 流程：步骤完成 → 按验收标准验收 → 标记 [x]。

## 通用规则

1. 代码文件单个不超过 300 行，超出须拆分（文档除外）
2. 长任务流程：先在任务目录写 steps.md（步骤）+ boundaries.md（边界）+ ui.md（UI 设计）→ 用户确认后开始执行 → 各步骤依次执行不再逐步确认 → 每步完成后验收并标记完成 → 超出 scope 时暂停询问
3. 每次验收完成后必须立即修改 workflow.md 将对应步骤标记 [x]，不得遗漏
4. 开始长任务前先读 workflow.md，据此创建任务清单（TodoList）并在执行中同步实时更新
5. Agent 改动须编译通过（`go build`；交叉编译 `CGO_ENABLED=0 GOOS=linux GOARCH=amd64`），部署仅替换测试节点并保留旧二进制备回退
6. 红线：不动生产环境；不提交密钥凭据；不未经确认删除文件或重置数据；不改 scope 目标外的模块
7. 修改完成后总结改动内容与效果；踩坑与决策记入对应任务 spec.md 进度记录

## 任务列表

### 服务信息卡片 SSE 实时化（已完成）→ [service-info-sse/](./service-info-sse/)

- [x] 后端数据基础：实际运行镜像/app 标签/快照构建 —— 验收：HTTP 列表镜像正确 ✅
- [x] SSE 流接口：stream（快照+增量+心跳）+ envs —— 验收：滚动更新持续收到变更事件 ✅
- [x] 前端改造：卡片订阅 SSE、openEnv 改 HTTP、断连回退 —— 验收：15 卡片实时渲染 ✅
- [x] 回归验证 —— 验收：原有功能全正常 ✅

### 构建取消 + 重跑逻辑修复（已完成）→ [build-cancel-rerun/](./build-cancel-rerun/)

- [x] Agent 取消终止能力：exec/cancel/server（DOCKER_BUILDKIT=0、docker 路径统一、异步 kill）—— 验收：go build 编译通过 ✅
- [x] 取消意图贯通与状态保护：build.go 启动检查 CancelRequested、complete_build 防复活 —— 验收：cancelled 不被回调覆盖 ✅
- [x] 重跑逻辑修复：禁部署步骤重跑、拦 pending 重复触发 —— 验收：两类请求被拦截且报错明确 ✅
- [x] 编译部署与实测回归 —— 验收：三阶段取消即时终止、各步骤重跑正常 ✅

### 构建页面卡顿优化（已完成）→ [build-page-freeze/](./build-page-freeze/)

> 根因：① SSE 长连接占满 gunicorn 16 线程（env 流永不结束、日志代理断开后残留）→ 普通请求排队；② 总览↔步骤切换断开重连全量重传日志 → 前端渲染卡死

- [x] 服务端 SSE 连接生命周期治理 + 容量加固：proxy 断连即释放、pump 随主生成器退出、env 流空闲自动关、threads 16→48、DB 池 15→30 —— 验收：反复开关抽屉无残留阻塞线程、配置生效 ✅
- [x] 前端日志单连接 + 本地切分：仅 1 条 all SSE、按步骤标记本地分段、渲染限量（两个页面同步改）—— 验收：切换 <200ms 无卡顿、含重跑场景日志正确 ✅
- [x] 回归与收尾：触发/取消/重跑、deploy 日志、流自动关闭与页面离开释放 —— 验收：全流程无残留连接无报错 ✅

### 构建自填充服务目录（已完成）→ [build-waiting-dirs/](./build-waiting-dirs/)

> 方案（v2）：模板服务目录留空 → 编译后跳过收集/打镜像报 success → 部署步骤 waiting → 平台浏览编译后目录勾选回填模板 → 重新触发构建（v1 挂起-续跑已废弃：任务参数一次性下发 Agent）

- [x] Agent 跳过上报：build.go 空服务目录 → Step3~5 skipped + success —— 验收：go build 通过 ✅
- [x] Master 状态机：skipped 步骤支持 + 部署步骤 waiting（auto_deploy 接入）+ configure_artifact_dirs；删除 v1 挂起/续跑/超时扫描 —— 验收：语法检查通过 ✅
- [x] Master 接口：code-dirs 放开状态限制、/continue 改 /configure-dirs（仅回填模板）—— 验收：路由注册、权限生效 ✅
- [x] 前端：部署等待「配置服务目录」按钮 + 勾选回填弹窗 + 未配置服务时显示「暂未配置服务」+ 状态映射清理（两页面同步）—— 验收：JS 语法通过 ✅
- [x] 编译部署 + 实测回归 —— 验收：跳过→部署等待→勾选回填→重建全链路跑通、已配置构建回归正常 ✅

### 调度中心节点目录浏览（已完成）→ [agent-dir-browser/](./agent-dir-browser/)

> 方案：Agent 接口（节点侧路径管控）而非 SSH；只读单层目录、仅限工作目录内；独立权限 `op:agent_dir`

- [x] Agent 目录接口 + 路径管控：server.go handleList（Clean+Join+Abs+EvalSymlinks 双重前缀校验）—— 验收：go build 通过、越界全拒 ✅
- [x] Master 转发接口 + 权限码：schedule dirs 接口（op:agent_dir）+ menu_seed 追加 —— 验收：无权限 403、有权限返回单层目录 ✅
- [x] 前端目录浏览 UI：SchedulePage 选节点逐级浏览（面包屑+单层列表）—— 验收：入口受权限控制、可逐级导航 ✅
- [x] 编译部署 + 实测回归 —— 验收：正常浏览/越界拒绝/无权限 403/离线友好报错，现有接口不受影响 ✅

### 服务信息环境收藏侧栏（规划中）→ [env-favorites-bar/](./env-favorites-bar/)

> 方案（落库版）：服务信息页（deploy/ServiceInfoPage.js）左侧可收起「环境收藏栏」+ 右侧工具栏（新增「收藏此环境」按钮）+ 右侧服务卡片区；收藏「项目+环境」二元组，点击卡片回填并触发展示、卡片可取消收藏；**数据落 MySQL 按用户（`g.current_user.id`）绑定，不用 Redis**（项目约定 MySQL 为唯一事实源）。范围扩大为 前端+后端+数据库。详见 steps.md / boundaries.md / ui.md

- [ ] 后端模型+建表：`deploy_env_favorites`（user_id 索引 + 唯一约束 user/project/env）—— 验收：表存在、唯一约束生效
- [ ] 后端接口：list/add/delete，按 g.current_user.id 隔离、删除校验归属 —— 验收：三接口通、跨用户不可见、删他人 403
- [ ] 前端三块布局：左可收起收藏栏 + 右工具栏 + 右服务卡片（原逻辑零改动移入）—— 验收：折叠展开正常、主区外观不变、无报错
- [ ] 工具栏「收藏此环境」按钮 + 写入接口 —— 验收：选齐可用、收藏即时入栏、刷新从库恢复
- [ ] 侧栏卡片：取消收藏 / 点击回填触发 / 当前高亮 / 空态 —— 验收：取消即消失、点击正确切换加载、环境已删降级
- [ ] 验收与回归：node --check + 接口手测 + 现有功能回归 —— 验收：收藏链路通、原功能无影响
