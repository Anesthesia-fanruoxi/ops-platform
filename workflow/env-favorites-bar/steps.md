# 步骤规划：服务信息页「环境收藏侧栏」（按用户落库版）

> 任务目录：`workflow/env-favorites-bar/`
> 关联规则：先在任务目录写 steps.md + boundaries.md + ui.md → 用户确认后开始执行 → 各步骤依次执行不再逐步确认 → 每步完成后验收并标记。
> 当前结论：**收藏数据落 MySQL，按当前用户（`g.current_user.id`）绑定**，不用 Redis（项目约定 MySQL 为唯一事实源，Redis 仅加速层）。

## 目标

在服务信息页（`static/js/modules/deploy/ServiceInfoPage.js`）提供「环境收藏」能力：
- 选中「项目 + 环境」后，点工具栏新增的「★ 收藏此环境」按钮，把该组合收藏；
- 左侧可收起/展开的「收藏栏」以卡片列出当前用户的所有收藏；
- 卡片带「取消收藏」按钮（删除即从侧栏消失），点击卡片即自动填充项目 + 环境并触发服务展示；
- 收藏持久化到数据库，按用户隔离，跨设备/会话一致。

收藏项 = 二元组 `{ project_id, project_name, env_id, env_name }`，与现有 `selectedProject / selectedEnv` 完全对齐（环境依附项目）。

---

## 步骤拆解

### 步骤 1 · 后端数据模型 + 建表（落库、用户绑定）
- 在 `modules/deploy/models.py`（或 `modules/cicd/models.py`，执行时确认）新增：
  ```python
  class DeployEnvFavorite(db.Model):
      __tablename__ = 'deploy_env_favorites'
      id = db.Column(db.Integer, primary_key=True)
      user_id = db.Column(db.Integer, nullable=False, index=True)
      project_id = db.Column(db.Integer, nullable=False)
      project_name = db.Column(db.String(50), default='')
      env_id = db.Column(db.Integer, nullable=False)
      env_name = db.Column(db.String(50), default='')
      created_at = db.Column(db.DateTime, default=datetime.now)
      __table_args__ = (db.UniqueConstraint('user_id','project_id','env_id', name='uq_user_proj_env'),)
      def to_dict(self): ...   # 返回 id / project_id / project_name / env_id / env_name / created_at
  ```
- 确认 `bootstrap.py` 的 `db.create_all()` 能覆盖到该模型所在模块（同模块其他表已自动建，则无需额外处理）；如未覆盖，补一处 import。
- 验收：`python -c "from core.db import db; db.create_all()"`（或重启 Master）后，`deploy_env_favorites` 表存在；唯一约束生效。

### 步骤 2 · 后端接口（list / add / delete，按用户隔离）
- 在 deploy 蓝图（`modules/deploy/routes.py` 或 `favorite_api.py`）新增接口，全部经 `check_auth` 钩子拿到 `g.current_user`：
  - `GET  /api/deploy/service-info/favorites` → 返回当前用户收藏列表（按 `created_at` 升序）。
  - `POST /api/deploy/service-info/favorites` → body `{ project_id, env_id }`；服务端回查 `projects`/`environments` 补全 `project_name`/`env_name`；唯一约束冲突则幂等返回已存在项；返回新记录。
  - `DELETE /api/deploy/service-info/favorites/<id>` → 仅删除 `user_id == 当前用户` 的记录（防越权删他人收藏）。
- 权限：沿用现有鉴权（`check_auth` 已注入 `g.current_user`），不新增权限码；越权/不存在返回 403/404。
- 验收：用 curl/Postman 验证三接口；A 用户看不到 B 用户收藏；重复收藏幂等；删他人 id 返回 403。

### 步骤 3 · 前端布局重构（三块：可收起收藏栏 + 工具栏 + 服务卡片）
- 根 `<div>` 改为 `.svc-layout`（flex）：
  - 左：`<aside class="env-fav-bar" :class="{collapsed: favCollapsed}">`，含头部「环境收藏」+ 折叠/展开按钮 + 列表/空态；
  - 右：`.svc-main` 包裹现有 toolbar + 分割线 + 服务卡片区（**原逻辑零改动移入**）。
- 收藏栏折叠：点击头部按钮切 `favCollapsed`，折叠态仅留一条窄竖条 + 展开图标，hover/点击展开。
- 对应 CSS 写入 deploy 模块样式文件：`.svc-layout` / `.env-fav-bar`（含 `.collapsed`）/ `.svc-main`。
- 验收：默认展开显示空白栏；折叠/展开动画正常；主区外观与改动前一致；控制台无报错。

### 步骤 4 · 工具栏「收藏此环境」按钮 + 收藏写入
- 在现有 toolbar 末尾新增 `★ 收藏此环境` 按钮（`type="primary" plain size="small"`）：
  - `selectedProject` 或 `selectedEnv` 未选齐 → `disabled` + 灰显；
  - 点击 `addFavorite()`：调用 `POST /api/deploy/service-info/favorites`，成功后把返回项 `unshift` 进 `favorites` 并 `ElMessage.success('已收藏')`；已收藏（接口幂等返回存在项）→ 提示「已收藏」不重复加。
- `mounted()` 时 `GET /api/deploy/service-info/favorites` 拉取当前用户收藏填入 `favorites`。
- 验收：选齐项目环境后按钮可用；收藏成功即时出现在侧栏；未选齐禁用；刷新后从库恢复。

### 步骤 5 · 侧栏卡片（取消收藏 + 点击触发 + 当前高亮）
- 列表项 `.fav-card`：上行项目名（粗）+ 下行环境名；右侧「取消收藏」按钮（`removeFavorite(id)` → `DELETE` 成功后从 `favorites` 过滤，卡片消失）。
- 点击卡片（`selectFavorite(item)`）：
  1. 跨项目 → `selectedProject = item.project_name` 并触发 `onProjectChange()` 加载 `envList`，`nextTick`/短延时后置 `selectedEnv = item.env_name`；
  2. 同项目换环境 → 直接置 `selectedEnv`；
  3. 调 `loadServices()` 触发服务展示；同步高亮。
- 当前选中项（与 `selectedProject + selectedEnv` 相等）加 `.is-active`。
- 容错：目标环境在当前 `envList` 不存在（被删）→ 降级仅选项目 + `ElMessage.warning('该环境已不存在，请重新选择')`。
- 空态：居中「暂无收藏，选好环境后点「收藏此环境」」。
- 验收：点击卡片正确切换并加载对应服务；取消后即时消失；当前项高亮与下拉选中态一致；环境被删友好降级。

### 步骤 6 · 边界、健壮性、验收与回归
- 去重（唯一约束 + 前端幂等提示）、越权删除防护（后端 `user_id` 校验）。
- 接口异常（网络/500）→ `ElMessage.error` 并保留现有选择，不白屏。
- 窄屏（`<1100px`）侧栏宽度自适应；`<768px` 侧栏移顶部（`flex-direction:column`）。
- `node --check` 通过；Python 端接口语法/导入正常。
- 手动验证全流程：选环境→收藏→折叠/展开→点卡片回填触发→取消消失→刷新从库恢复→换账号隔离。
- 回归：原有项目/环境下拉、服务卡片 SSE、构建 SSE、Nacos、快捷部署、环境变量弹窗**全部不受影响**。
- 踩坑与决策记入本文件「进度记录」。

---

## 进度记录

| 步骤 | 状态 | 备注 |
|------|------|------|
| 1 后端模型+建表 | 待执行 | 表 `deploy_env_favorites`，user_id 索引+唯一约束 |
| 2 后端接口 | 待执行 | list/add/delete，按 g.current_user.id 隔离 |
| 3 前端三块布局 | 待执行 | 左可收起栏 + 右工具栏 + 右服务卡片 |
| 4 收藏按钮+写入 | 待执行 | toolbar 加「收藏此环境」 |
| 5 侧栏卡片交互 | 待执行 | 取消收藏 / 点击回填触发 / 高亮 |
| 6 验收回归 | 待执行 | node --check + 接口手测 + 回归 |
