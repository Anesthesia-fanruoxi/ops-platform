# 边界与红线：服务信息页「环境收藏侧栏」（按用户落库版）

> 本文件界定本次任务的 scope 内外、约束与红线。超出边界时暂停并询问，不得自行扩展。

## 一、范围（In Scope）

**前端 + 后端 + 数据库三者联动**（相比初版 localStorage 方案，本次按用户落库，范围扩大）：

1. **前端**：`static/js/modules/deploy/ServiceInfoPage.js` + deploy 模块样式文件
   - 三块布局：左侧可收起「环境收藏栏」+ 右侧上方工具栏（原功能不变，新增「★ 收藏此环境」按钮）+ 右侧下方服务卡片区。
   - 收藏栏：卡片列表 / 取消收藏 / 点击回填触发 / 当前高亮 / 空态 / 折叠展开。
2. **后端**：`modules/deploy/` 下新增模型 + 接口（list / add / delete），经 `g.current_user.id` 绑定用户。
3. **数据库**：新增表 `deploy_env_favorites`（或 `cicd_env_favorites`，执行时确认模块归属），由 `bootstrap.py` 的 `db.create_all()` 自动建表。

## 二、明确不做（Out of Scope）

- **不引入 Redis 存收藏**。Redis 在本项目定位为"缓存/锁/运行时状态加速层，MySQL 唯一事实源"（见 `core/redis_client.py`），用户持久配置不落 Redis。
- **不做跨用户共享 / 公开收藏 / 收藏分组 / 拖拽排序 / 批量收藏**等高级能力。
- **不替换**现有「项目 / 环境」下拉框，仅作为补充快捷方式。
- **不动**范围外的模块：CICD 配置页（`CicdConfigPage.js`）、调度中心（`SchedulePage.js`）、Agent、Nacos/Harbor 等业务逻辑。
- **不新增权限码**：复用现有 `check_auth` 注入的 `g.current_user`，收藏仅对自身数据可见/可改。
- **不引入**新第三方依赖 / 图标库；沿用 Element Plus + 现有 `ajax` 模式 + emoji/SVG。

## 三、技术约束

- 前端模板标签沿用项目约定 `[[ ]]`（非默认 `{{ }}`）。
- 改动后 JS 必须通过 `node --check` 语法校验；Python 改动需 `python -c` 导入/建表验证。
- 沿用亮色主题配色（主色 `#409eff`、次级灰 `#909399`、边框 `#ebeef5`、浅底 `#fafbfc`/`#ecf5ff`）。
- 接口返回结构遵循项目现有约定（`{code, msg, data}`）。

## 四、红线（必须遵守）

1. 不动生产环境；不提交密钥 / 凭据；不未经确认删除文件或重置数据。
2. 不改 scope 目标外的模块与接口。
3. **收藏数据必须按 `user_id` 隔离**：列表仅查当前用户；删除必须校验 `user_id == g.current_user.id`，禁止越权删他人收藏。
4. 任何超出上述边界的需求（如收藏分组、Redis 缓存层、跨用户共享）须暂停并提问，不得擅自实现。

## 五、假设（如与预期不符请指出）

- 收藏 = `（项目, 环境）` 二元组；环境依附于项目；以 `project_id + env_id` 唯一标识。
- 持久化介质 = **MySQL 表**，按 `g.current_user.id` 绑定；非 Redis、非 localStorage。
- 接口前缀沿用 ServiceInfoPage 既有 `/api/deploy/service-info/*`。
- 侧栏默认宽度 ~220px 可折叠；具体视觉以 `ui.md` 为准。
