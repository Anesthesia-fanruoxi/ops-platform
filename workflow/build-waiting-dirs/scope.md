# 范围边界：构建自填充服务目录（部署步骤等待勾选回填后重建）

## 目标内（In Scope）

1. 后端模板允许服务目录（`artifact_dirs`）留空：放开模板创建/编辑的必填校验
2. 空服务目录后端构建：clone+编译成功后跳过产物收集/Docker Build/Push（步骤 skipped），构建正常 success
3. 部署步骤 waiting：auto_deploy 检测后端无服务目录时置部署步骤 waiting，不执行部署
4. Master 接口：浏览该构建 code 目录（`GET /builds/<id>/code-dirs`，不限构建状态）、勾选回填模板（`POST /builds/<id>/configure-dirs`，仅改模板）
5. 前端构建面板（ServiceInfoPage.js / ManagePage.js 两处）：部署等待时「配置服务目录」按钮 + 勾选弹窗；构建范围未配置服务时显示「暂未配置服务」
6. Agent 交叉编译（linux/amd64）并部署测试节点（保留旧二进制备回退）

## 目标外（Out of Scope）

1. 前端构建（frontend 类型，dist 固定）不涉及该逻辑
2. 产物目录（`artifact_dir`）的勾选填充——本次仅服务目录
3. 目录浏览的文件内容查看 / 写操作（只读列举，复用既有 /list 边界）
4. 已填服务目录的构建行为不变（不改动正常构建链路）
5. 勾选回填后不自动重建：由用户手动重新触发构建（任务参数一次性下发 Agent，不引入续跑机制）

## 涉及对象

| 类型 | 名称/路径 | 说明 |
| --- | --- | --- |
| Agent | `agent/build.go` | Step3 空服务目录跳过 3~5 步报 success |
| Master 服务 | `build_service.py`、`auto_deploy.py`、`dispatch_service.py` | skipped/waiting 步骤支持 + configure_artifact_dirs；部署等待；移除 v1 超时扫描 |
| Master API | `build_api.py`、`agent_comm_api.py`、`template_api.py`、`routes.py` | code-dirs/configure-dirs 接口 + 回调白名单 + 校验放开 |
| 前端 | `ServiceInfoPage.js`、`ManagePage.js`、`CicdConfigPage.js` | 部署等待按钮/弹窗/空态 / 模板页提示 |
| 数据 | build.json 步骤状态 | 新增取值 `skipped`（步骤）、部署步骤新增 `waiting`；DB 无表结构变更 |
| 环境 | 测试环境构建节点 | Agent 部署仅替换测试节点二进制，保留旧二进制备回退 |

## 变更记录

| 日期 | 变更内容 | 原因 |
| --- | --- | --- |
| 2026-08-19 | 初始范围确定（v1：挂起-续跑方案） | 磁盘挂起复用重跑机制 |
| 2026-08-19 | 方案改为 v2：部署步骤等待 + 回填模板后重建 | 用户修正：任务参数一次性下发 Agent，续跑链路不成立；等待点移至部署步骤，勾选仅回填模板，重新构建走完整流程；同时要求服务未配置时空态显示「暂未配置服务」 |
