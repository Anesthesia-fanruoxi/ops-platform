# UI 设计：服务信息页「环境收藏侧栏」（按用户落库版）

> 视觉规范，供步骤 3/4/5 实现对齐。整体沿用项目既有亮色主题与 Element Plus 风格。

## 一、整体布局（三块）

```
┌──────────┬──────────────────────────────────────────────────┐
│ « 环境收藏 │ 工具栏：项目▼ 环境▼ 刷新 Nacos 快捷部署 运行状态 ★收藏此环境 │  ← .svc-main 内，原样保留 + 新增按钮
│   ▸(展开) │ ────────────────────────────────────────────── │
│ ────────  │  服务卡片区 / 弹窗 / 抽屉（原样）                    │
│ [卡片A]   │                                                   │
│  项目A     │                                                   │
│  环境X ●   │                                                   │
│  ✕取消     │                                                   │
│ [卡片B]   │                                                   │
│  项目B     │                                                   │
│  环境Y     │                                                   │
│  ✕取消     │                                                   │
└──────────┴──────────────────────────────────────────────────┘
   ▲ .env-fav-bar（左，~220px，可折叠）      ▲ .svc-main（右，flex:1）
```

- 根容器 `.svc-layout`：`display:flex; gap:16px; align-items:flex-start;`
- `.env-fav-bar`：宽 `220px`，`flex-shrink:0`，背景 `#fafbfc`，右边框 `1px solid #ebeef5`，圆角 `8px`，`padding:12px`。
- `.svc-main`：`flex:1; min-width:0;`（防内部表格/代码撑破）。
- 折叠态 `.env-fav-bar.collapsed`：宽 `44px`，仅显示竖排「环境收藏」标题 + 展开箭头图标，hover 整条可点展开；展开后恢复 `220px`。

## 二、侧栏头部

- 标题「环境收藏」：`font-size:14px; font-weight:600; color:#303133;`。
- 右侧「折叠/展开」切换按钮：`type="text" size="small"`，图标用 `«` / `»`（或内联 SVG），点击切 `favCollapsed`。

## 三、工具栏新增「★ 收藏此环境」按钮

- 位置：现有工具栏末尾（刷新/Nacos/快捷部署/运行状态之后），`type="primary" plain size="small"`。
- 未选齐项目/环境 → `disabled` 灰显；已选齐 → 可点。
- 点击 → `POST /api/deploy/service-info/favorites`，成功后 `ElMessage.success('已收藏')` 并即时出现在侧栏；接口返回"已存在"→ 提示「已收藏」不重复加。

## 四、收藏卡片（.fav-card）

- 容器：圆角 `8px`、白底 `#fff`、边框 `1px solid #ebeef5`、`padding:8px 10px`、hover 轻微上浮 `translateY(-1px)` + 阴影 `0 2px 8px rgba(64,158,255,.10)`；整卡可点击（回填触发）。
- 当前选中项（`.is-active`）：左侧 `4px solid #409eff` 色条 + 极浅蓝底 `#ecf5ff`。
- 内容两行：
  - 上行：项目名，`font-weight:600; font-size:13px; color:#303133;`
  - 下行：环境名，`font-size:12px; color:#909399;`，行首小圆点 `●`（当前选中变蓝）。
- 右侧「✕ 取消收藏」按钮：`type="text" size="small"`，默认半透明，hover 整卡时显现红色 `#f56c6c`；点击调 `removeFavorite(id)`（`DELETE`）成功后卡片从列表消失。

## 五、空态

- 居中提示：「暂无收藏，选好环境后点「收藏此环境」」
- 样式：`color:#c0c4cc; font-size:12px; text-align:center; padding:24px 8px;`

## 六、交互态

| 状态 | 表现 |
|------|------|
| 未选齐项目/环境 | 「收藏此环境」按钮禁用灰显 |
| 已收藏当前项 | 点击收藏提示「已收藏」，不重复添加 |
| 当前选中项 | 左侧蓝条 + 浅蓝底 + 蓝点，与下拉框选中态同步 |
| 取消收藏 | 调 DELETE，成功后卡片即时消失 |
| 点击卡片 | 回填项目+环境并 `loadServices()` 触发服务展示 |
| 目标环境已不存在 | 降级仅选项目 + `ElMessage.warning('该环境已不存在，请重新选择')` |
| hover 卡片 | 上浮 + 阴影；✕ 显现红色 |
| 侧栏折叠 | 仅留 44px 竖条 + 展开箭头，点击/ hover 展开 |

## 七、图标与配色基线

- 图标用 emoji（★ / ● / ✕ / « / »）或内联 SVG，**不引入图标库**。
- 主色 `#409eff`、成功 `#67c23a`、危险 `#f56c6c`、次级文字 `#909399`、边框 `#ebeef5`、浅底 `#fafbfc` / `#ecf5ff`，与现有 `svc-*` 系列一致。
- 窄屏（`<1100px`）侧栏缩至 `160px`；`<768px` 侧栏移顶部（`flex-direction:column`），不遮挡主区。
