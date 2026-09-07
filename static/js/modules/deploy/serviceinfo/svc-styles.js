// ============================================================
// 服务信息页样式注入（带版本号：样式改动后强制覆盖旧节点，避免硬刷新后旧 CSS 缓存不更新）
// ============================================================
(function() {
  const OLD = document.getElementById('service-info-style');
  if (OLD) OLD.remove();
  const style = document.createElement('style');
  style.id = 'service-info-style';
  style.textContent = `
.svc-log-terminal {
  background: #0a2e3c; color: #a8bcc0; border-radius: 6px;
  padding: 12px 14px; height: 74vh; overflow-y: auto;
  font-family: Consolas, 'Courier New', monospace; font-size: 12.5px;
  line-height: 1.6; white-space: pre-wrap; word-break: break-all;
}
.svc-yaml-pre {
  margin: 0; padding: 12px 14px; background: #f6f8fa; border-radius: 6px;
  max-height: 62vh; overflow: auto; font-size: 12.5px;
  font-family: Consolas, Menlo, monospace; white-space: pre;
}
.svc-copy-btn {
  position: absolute; top: 8px; right: 10px; z-index: 2;
  padding: 2px 10px; font-size: 12px; line-height: 1.6;
  color: #555; background: #fff; border: 1px solid #dcdfe6;
  border-radius: 4px; cursor: pointer;
}
.svc-copy-btn:hover { color: #409eff; border-color: #c6e2ff; background: #ecf5ff; }
/* 配置弹窗自适应高度：上下各留 10%，内容擑满 */
.svc-config-dialog { height: 80vh; display: flex; flex-direction: column; --el-dialog-bg-color: #0a2e3c; }
.svc-config-dialog .el-dialog { background: #0a2e3c; }
.svc-config-dialog .el-dialog__header { background: #0a2e3c !important; border-bottom: 1px solid #1c4a5e; }
.svc-config-dialog .el-dialog__title { color: #a8bcc0 !important; font-size: 15px; }
.svc-config-dialog .el-dialog__headerbtn .el-dialog__close { color: #7fa3ad; }
.svc-config-dialog .el-dialog__headerbtn .el-dialog__close:hover { color: #d4e6ea; }
.svc-config-dialog .el-dialog__body { background: #0a2e3c !important; padding-top: 12px; }
.svc-config-header { display: flex; align-items: center; gap: 12px; width: 100%; }
.svc-config-title { color: #a8bcc0; font-size: 15px; font-weight: 600; white-space: nowrap; }
.svc-config-count { color: #7fa3ad; font-size: 12px; white-space: nowrap; }
.svc-cfg-code { position: relative; flex: 1; min-height: 0; display: flex; border-radius: 6px; overflow: hidden; background: #0a2e3c; border: 1px solid #1c4a5e; }
.svc-cfg-gutter { width: 46px; flex-shrink: 0; overflow: hidden; background: #0d3545; color: #5c8490; text-align: right; padding: 12px 8px 12px 0; font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7; user-select: none; }
.svc-cfg-gutter-line { white-space: nowrap; }
.svc-config-dialog .el-dialog__body { flex: 1; min-height: 0; overflow: auto; }
.svc-config-dialog .el-dialog__body > div { height: 100%; display: flex; flex-direction: column; }
.svc-config-dialog .el-textarea { flex: 1; min-height: 0; display: flex; }
.svc-config-dialog .el-textarea__inner { flex: 1; height: 100%; }
/* 工具栏 / 护眼查看区 / 搜索高亮 */
.svc-cfg-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.svc-cfg-matches { color: #888; font-size: 12px; }
.svc-cfg-content { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }
.svc-cfg-copy-btn {
  position: absolute; top: 8px; right: 8px; z-index: 2;
  background: rgba(10, 46, 60, 0.9); border: 1px solid #2f5a6b; color: #a8bcc0;
}
.svc-cfg-copy-btn:hover { color: #d4e6ea; border-color: #3f7a8f; background: rgba(20, 60, 78, 0.95); }
/* Nacos 配置弹窗：深色适配（搜索框/普通按钮） */
.svc-config-dialog .el-input__wrapper { background: #0d3545; box-shadow: 0 0 0 1px #1c4a5e inset; }
.svc-config-dialog .el-input__inner { color: #a8bcc0; }
.svc-config-dialog .el-input__inner::placeholder { color: #5c8490; }
.svc-config-dialog .el-input__clear { color: #5c8490; }
/* 搜索输入框内置放大镜图标（prefix 内嵌，青色，替代搜索按钮） */
.svc-input-icon { font-size: 13px; line-height: 1; color: #3aa3b8; display: inline-flex; align-items: center; }
.svc-log-dialog .svc-input-icon { color: #3aa3b8; }
.svc-config-dialog .el-button:not(.el-button--primary):not(.el-button--text) {
  background: #0d3545; border-color: #1c4a5e; color: #a8bcc0;
}
.svc-config-dialog .el-button:not(.el-button--primary):not(.el-button--text):hover {
  color: #d4e6ea; border-color: #3f7a8f; background: #123f52;
}
/* Nacos 配置弹窗滚动条：品牌靛蓝。经设计令牌变量覆盖（common.css 基座），
   含上下限位箭头着色；scrollbar-color 由变量继承兜底，避免被全局浅灰压过 */
.svc-config-dialog { --sb-size: 10px; --sb-thumb: #2f5a6b; --sb-thumb-hover: #3f7a8f; --sb-track: rgba(47, 90, 107, 0.18); }
.svc-config-pre { scrollbar-color: #2f5a6b rgba(47, 90, 107, 0.18); scrollbar-width: thin; }
.svc-config-pre::-webkit-scrollbar { width: 10px; height: 10px; }
.svc-config-pre::-webkit-scrollbar-track { background: transparent; }
.svc-config-pre::-webkit-scrollbar-thumb { background: #2f5a6b; border: 2px solid transparent; background-clip: padding-box; border-radius: 5px; }
.svc-config-pre::-webkit-scrollbar-thumb:hover { background: #3f7a8f; border: 2px solid transparent; background-clip: padding-box; }
.svc-config-dialog ::-webkit-scrollbar-button { background: #2f5a6b; }
.svc-config-dialog ::-webkit-scrollbar-button:hover { background: #3f7a8f; }
.svc-config-dialog ::-webkit-scrollbar-button:vertical:start:decrement, .svc-config-dialog ::-webkit-scrollbar-button:vertical:end:increment { height: 14px; }
.svc-config-pre {
  position: relative; z-index: 0;   /* 层叠上下文：段落参考线走 z-index:-1，压在文字下、底色上 */
  flex: 1; min-height: 0; margin: 0; padding: 12px 14px; overflow: auto;
  background: #0a2e3c; color: #a8bcc0; border-radius: 6px;
  font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7;
}
/* YAML 段落缩进参考线：图层零尺寸不影响 pre 滚动区，竖线由 JS 按行高/字符宽定位 */
.svc-cfg-guides { position: absolute; left: 0; top: 0; width: 0; height: 0; z-index: -1; }
.svc-cfg-guide {
  position: absolute; width: 1px; background: rgba(168, 188, 192, 0.09);
  pointer-events: none;
}
.svc-cfg-guide.lvl-0 { background: rgba(168, 188, 192, 0.22); }
.svc-cfg-guide.lvl-1 { background: rgba(168, 188, 192, 0.16); }
.svc-cfg-guide.lvl-2 { background: rgba(168, 188, 192, 0.12); }

/* 日志弹窗：整体 Nacos 配置护眼背景色 */
.svc-log-dialog { --el-dialog-bg-color: #0a2e3c; }
.svc-log-dialog .el-dialog { background: #0a2e3c; }
.svc-log-dialog .el-dialog__header { background: #0a2e3c !important; border-bottom: 1px solid #1c4a5e; }
.svc-log-dialog .el-dialog__title { color: #a8bcc0 !important; font-size: 15px; }
.svc-log-dialog .el-dialog__headerbtn .el-dialog__close { color: #7fa3ad; }
.svc-log-dialog .el-dialog__headerbtn .el-dialog__close:hover { color: #d4e6ea; }
.svc-log-dialog .el-dialog__body { background: #0a2e3c !important; padding-top: 12px; }
.svc-log-match { background: rgba(230, 162, 60, 0.28); }
.svc-log-time { color: #6cb6e8; }
.svc-log-method { color: #c678dd; }
.svc-log-line { color: #e5c07b; }


.svc-log-header { display: flex; align-items: center; gap: 12px; width: 100%; padding-right: 30px; }
.svc-log-title { font-size: 15px; color: #a8bcc0; white-space: nowrap; }
.svc-log-count { font-size: 12px; color: #6f94a0; background: rgba(168,188,192,.12); padding: 2px 8px; border-radius: 10px; white-space: nowrap; }
.svc-log-header-tools { display: inline-flex; align-items: center; gap: 6px; margin-left: auto; }
.svc-log-fs-tip { color: #6f94a0; font-size: 12px; white-space: nowrap; }
/* 日志全屏模式：终端铺满窗口剩余高度 */
.svc-log-dialog.svc-log-fs .svc-log-terminal { height: calc(100vh - 120px); }
.svc-log-status { display: inline-flex; align-items: center; gap: 6px; color: #a8bcc0; font-size: 12px; white-space: nowrap; }
/* 日志弹窗控件全暗色：输入框/下拉/按钮去白底 */
.svc-log-dialog .el-input__wrapper {
  background: #0f3a4c;
  box-shadow: 0 0 0 1px #1c4a5e inset;
}
.svc-log-dialog .el-input__inner { color: #a8bcc0; }
.svc-log-dialog .el-input__inner::placeholder { color: #6f94a0; }
.svc-log-dialog .el-select__caret { color: #6f94a0; }
.svc-log-dialog .el-button {
  background: #0f3a4c; border-color: #1c4a5e; color: #a8bcc0;
}
.svc-log-dialog .el-button:hover:not(:disabled) { background: #14465c; border-color: #2f5a6b; color: #d4e6ea; }
.svc-log-dialog .el-button:disabled { background: #0c3140; border-color: #164052; color: #4d6d78; }
/* 日志弹窗滚动条：品牌靛蓝。终端具体元素直接写实色，避免变量继承在深色容器失效回落浅灰；其余容器走变量 */
.svc-log-dialog { --sb-size: 8px; --sb-thumb: #2f5a6b; --sb-thumb-hover: #3f7a8f; --sb-track: rgba(47, 90, 107, 0.18); }
.svc-log-terminal { scrollbar-color: #2f5a6b rgba(47, 90, 107, 0.18); scrollbar-width: thin; }
.svc-log-terminal::-webkit-scrollbar { width: 8px; height: 8px; }
.svc-log-terminal::-webkit-scrollbar-track { background: transparent; }
.svc-log-terminal::-webkit-scrollbar-thumb { background: #2f5a6b; border-radius: 4px; }
.svc-log-terminal::-webkit-scrollbar-thumb:hover { background: #3f7a8f; }
.svc-log-dialog ::-webkit-scrollbar-button { background: #2f5a6b; }
.svc-log-dialog ::-webkit-scrollbar-button:hover { background: #3f7a8f; }
/* el-select 新版触发器（.el-select__wrapper）去白底 */
.svc-log-dialog .el-select__wrapper { background: #0f3a4c; box-shadow: 0 0 0 1px #1c4a5e inset; }
.svc-log-dialog .el-select__placeholder, .svc-log-dialog .el-select__selected-item { color: #a8bcc0; }
.svc-log-dialog .el-select__caret.el-icon, .svc-log-dialog .el-input__clear { color: #6f94a0; }
/* 下拉弹出层暗色（popper teleport 到 body，用 popper-class 单独着色） */
.svc-log-popper.el-popper { background: #0f3a4c; border: 1px solid #1c4a5e; }
.svc-log-popper .el-popper__arrow::before { background: #0f3a4c; border-color: #1c4a5e; }
.svc-log-popper .el-select-dropdown__item { color: #a8bcc0; }
.svc-log-popper .el-select-dropdown__item.is-hovering, .svc-log-popper .el-select-dropdown__item:hover { background: #14465c; color: #d4e6ea; }
.svc-log-popper .el-select-dropdown__item.is-selected { color: #6cb6e8; font-weight: 600; }
.svc-log-popper { --sb-thumb: #2f5a6b; --sb-thumb-hover: #3f7a8f; --sb-track: #0f3a4c; }

.bp-log-box {
  background: #0a2e3c;
  color: #a8bcc0;
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', 'Microsoft YaHei', monospace;
  font-size: 12px;
  line-height: 1.7;
  padding: 14px 18px;
  border-radius: 6px;
  height: calc(100vh - 210px);
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.bp-drawer {
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.28) !important;
  border-left: 3px solid #409eff;
}
.bp-drawer .el-drawer__header {
  background: #f0f6ff;
  border-bottom: 1px solid #d9e6f5;
  margin-bottom: 0;
  padding: 14px 20px;
}
.bp-drawer .el-drawer__body {
  background: #fafbfc;
  padding: 20px;
}
.bp-drawer .el-step__head,
.bp-drawer .el-step__title {
  cursor: pointer;
}
.bp-drawer .el-step__head:hover .el-step__icon {
  transform: scale(1.15);
  box-shadow: 0 0 0 4px rgba(64, 158, 255, 0.15);
}
.bp-drawer .el-step__title:hover {
  color: #409eff;
}
.bp-drawer .el-step__icon {
  transition: transform .15s, box-shadow .15s;
}
.bp-step-overview {
  font-size: 16px;
  line-height: 1;
}
.bp-drawer .el-step.bp-step-selected .el-step__icon {
  box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.45);
  border-color: #409eff;
}
.bp-drawer .el-step.bp-step-selected .el-step__title {
  color: #409eff;
  font-weight: 600;
}
.build-dialog {
  height: 75vh;              /* 上留 10vh + 高 75vh = 下留 15vh */
  margin-top: 10vh !important;
  margin-bottom: 15vh !important;
  display: flex;
  flex-direction: column;
}
.build-dialog .el-dialog__header {
  flex-shrink: 0;
}
.build-dialog .el-dialog__body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
}
.build-dialog .el-dialog__body .build-two-col {
  flex: 1;
  min-height: 0;
}
.build-dialog .el-dialog__footer {
  flex-shrink: 0;
}
.build-scope-box {
  width: 100%;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  background: #fafafa;
  padding: 8px;
}
.build-scope-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 10px 8px;
  border-bottom: 1px solid #ebeef5;
  margin-bottom: 8px;
}
.build-scope-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 412px;
  overflow-y: auto;
}
.build-two-col {
  display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
  min-height: 0;
}
.build-two-col .build-col {
  display: flex; flex-direction: column; min-height: 0; overflow: hidden;
}
.build-two-col .build-col-head { flex-shrink: 0; }
.build-two-col .svc-branch-tree {
  flex: 1; min-height: 0; max-height: none;
  overflow-y: auto;
}
.build-two-col .build-scope-list {
  flex: 1; min-height: 0; max-height: none;
}
.build-col {
  border: 1px solid #e4e7ed; border-radius: 8px; padding: 12px; background: #fafbfc;
  min-width: 0;
}
.build-col-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #ebeef5;
}
.build-col-title { font-size: 13.5px; font-weight: 600; color: #303133; }
.svc-branch-pane { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.svc-branch-pane .svc-branch-list { flex: 1; }
.svc-branch-group {
  font-size: 11.5px; color: #909399; background: #f5f7fa;
  padding: 4px 10px; position: sticky; top: 0; z-index: 1;
  border-bottom: 1px solid #ebeef5;
}
.svc-branch-recent-tag {
  background: #fdf6ec; color: #e6a23c; font-size: 10.5px; border-radius: 3px;
  padding: 0 4px; margin-right: 6px;
}
.svc-branch-item.recent { background: #fdf6ec; }
.svc-branch-item.recent:hover { background: #f5e7d0; }
.svc-col-loading { color: #909399; font-size: 12.5px; padding: 24px 0; text-align: center; }
.svc-col-empty { color: #c0c4cc; font-size: 12px; padding: 24px 0; text-align: center; }
/* 左栏分支平铺列表：直接展示全部，超出滚动 */
.svc-branch-list {
  flex: 1; min-height: 0; overflow-y: auto;
  border: 1px solid #e4e7ed; border-radius: 4px; background: #fff;
}
.svc-branch-item {
  padding: 6px 10px; font-family: monospace; font-size: 12.5px; color: #606266;
  cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  border-bottom: 1px solid #f0f2f5;
}
.svc-branch-item:hover { background: #f5f7fa; }
.svc-branch-item.active { background: #ecf5ff; color: #409eff; font-weight: 500; }
/* 右栏服务列表：直接铺满，独立滚动 */
.svc-service-list {
  flex: 1; min-height: 0; overflow-y: auto;
  display: flex; flex-direction: column; gap: 6px;
}
.svc-service-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 10px; border: 1px solid #e4e7ed; border-radius: 4px; background: #fff;
}
.svc-branch-tree {
  border: 1px solid #e4e7ed; border-radius: 4px; padding: 8px; background: #fff;
  max-height: 260px; overflow-y: auto;
}
.svc-branch-tree .el-tree { background: transparent; }
.svc-toolbar-lastbuild {
  display: flex; align-items: center; gap: calc(6px * var(--svc-k));
  font-size: 12px; color: #606266; cursor: pointer; user-select: none;   /* 工具栏摘要不随 --svc-k 缩放，保证小屏可读 */
  background: #f4f4f5; border-radius: 6px; padding: calc(4px * var(--svc-k)) calc(10px * var(--svc-k));
  transition: box-shadow .15s;
}
.svc-toolbar-lastbuild:hover { box-shadow: 0 0 0 3px rgba(64, 158, 255, 0.15); }
/* 构建记录弹窗：行可点击 */
.build-records-dialog .el-table__row { cursor: pointer; transition: background .15s; }
.build-records-dialog .el-table__row:hover { background: #ecf5ff !important; }
.svc-lb-label { color: #909399; flex-shrink: 0; }
.svc-lb-user { color: #303133; font-weight: 500; }
.svc-lb-branch { color: #409eff; font-family: monospace; }
.svc-lb-time { color: #c0c4cc; }
/* 工具栏与内容区之间的虚线分割线 */
.svc-toolbar-divider {
  border-top: 1px dashed #dcdfe6;
  margin: 0 0 var(--svc-gap);
}
/* 工具栏运行状态指示器：监听环境构建 SSE，无任务灰显，有任务橙色高亮 */
.svc-run-status {
  display: inline-flex; align-items: center; gap: calc(6px * var(--svc-k));
  border: 1px solid #e4e7ed; background: #fafafa; border-radius: 6px;
  padding: calc(4px * var(--svc-k)) calc(10px * var(--svc-k)); font-size: var(--svc-fs-sm); color: #909399;
  white-space: nowrap; user-select: none;
}
.svc-run-status.svc-run-active {
  border-color: #f3d19e; background: #fdf6ec; cursor: pointer;
  transition: box-shadow .15s;
}
.svc-run-status.svc-run-active:hover { box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.18); }
.svc-run-text { color: #e6a23c; font-weight: 600; }
.svc-run-idle { color: #909399; }
.svc-active-build {
  display: flex; align-items: center; gap: 8px;
  background: #fdf6ec; border: 1px solid #f3d19e; border-radius: 6px;
  padding: 7px 12px; margin-bottom: 8px; cursor: pointer;
  transition: box-shadow .15s;
}
.svc-active-build:hover { box-shadow: 0 0 0 3px rgba(230, 162, 60, 0.18); }
.svc-active-dot {
  width: calc(9px * var(--svc-k)); height: calc(9px * var(--svc-k)); border-radius: 50%;
  background: #e6a23c; flex-shrink: 0;
  animation: svc-blink 1s ease-in-out infinite;
}
@keyframes svc-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.svc-active-label { color: #e6a23c; font-weight: 600; font-size: 12.5px; flex-shrink: 0; }
.svc-active-no { font-family: Consolas, monospace; color: #303133; font-weight: 500; font-size: 12.5px; }
.svc-active-branch { color: #909399; font-size: 12px; }
.svc-active-tip { margin-left: auto; color: #c0c4cc; font-size: 11.5px; flex-shrink: 0; }
.svc-env-builds {
  background: #fff; border: 1px solid #e4e7ed; border-radius: 10px; padding: 10px 14px; margin-bottom: 12px;
}
.svc-env-builds-title { font-size: 13px; font-weight: 600; color: #303133; margin-bottom: 8px; }
.svc-env-builds-list { display: flex; flex-direction: column; gap: 6px; }
.svc-env-build { display: flex; align-items: center; gap: 10px; font-size: 12px; color: #606266; }
.svc-env-build-type { background: #ecf5ff; color: #409eff; border-radius: 4px; padding: 1px 6px; font-size: 11px; flex-shrink: 0; }
.svc-env-build-no { font-family: Consolas, monospace; color: #303133; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.svc-env-build-branch { color: #909399; flex-shrink: 0; }
.svc-env-build-status { font-weight: 500; flex-shrink: 0; }
.svc-env-build-status.bs-success { color: #67c23a; }
.svc-env-build-status.bs-running, .svc-env-build-status.bs-pending { color: #e6a23c; }
.svc-env-build-status.bs-failed { color: #f56c6c; }
.svc-env-build-time { margin-left: auto; color: #c0c4cc; font-size: 11.5px; flex-shrink: 0; }
.svc-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(var(--svc-card-min), 1fr));
  gap: var(--svc-gap);
  min-height: 80px;
}
.svc-card {
  border: 1px solid #e4e7ed; border-radius: 8px; padding: calc(12px * var(--svc-k)) calc(14px * var(--svc-k));
  background: #fff; transition: box-shadow .2s, transform .2s;
}
.svc-card:hover { box-shadow: 0 2px 12px rgba(0,0,0,.08); transform: translateY(-1px); }
.svc-card-head { display: flex; align-items: center; gap: calc(8px * var(--svc-k)); margin-bottom: calc(8px * var(--svc-k)); }
.svc-card-name { font-weight: bold; font-size: var(--svc-fs-lg); color: #303133; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.svc-card-replicas { font-size: var(--svc-fs-sm); color: #606266; background: #f0f2f5; padding: 1px calc(8px * var(--svc-k)); border-radius: 10px; flex-shrink: 0; }
.svc-card-dot { width: calc(10px * var(--svc-k)); height: calc(10px * var(--svc-k)); border-radius: 50%; flex-shrink: 0; }
.svc-card-dot.ok { background: #67c23a; }
.svc-card-dot.warn { background: #e6a23c; }
.svc-card-dot.err { background: #f56c6c; }
.svc-card-dot.off { background: #c0c4cc; }
.svc-card-row { display: flex; gap: calc(8px * var(--svc-k)); margin-bottom: calc(6px * var(--svc-k)); font-size: var(--svc-fs-md); align-items: flex-start; }
.svc-card-label { color: #909399; width: calc(34px * var(--svc-k)); flex-shrink: 0; line-height: calc(22px * var(--svc-k)); }
.svc-card-value { flex: 1; min-width: 0; line-height: calc(22px * var(--svc-k)); color: #606266; }
.svc-card-image { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.svc-card-actions { border-top: 1px dashed #ebeef5; margin-top: calc(8px * var(--svc-k)); padding-top: calc(8px * var(--svc-k)); display: flex; gap: calc(4px * var(--svc-k)); }
.svc-empty { padding: calc(40px * var(--svc-k)) 0; text-align: center; }
/* 首次进入、未选环境时的引导提示 */
.svc-empty-hint {
  grid-column: 1 / -1; padding: calc(80px * var(--svc-k)) 0;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.svc-empty-icon { font-size: calc(44px * var(--svc-k)); line-height: 1; opacity: .7; margin-bottom: 8px; }
.svc-empty-text { font-size: var(--svc-fs-title, 15px); color: #606266; font-weight: 500; }
.svc-empty-sub { font-size: var(--svc-fs-md); color: #c0c4cc; }
.svc-config-pre code { background: transparent; font-family: inherit; font-size: inherit; }
/* hljs 深青蓝底配色（与部署日志同款护眼色） */
.svc-config-pre .hljs-comment, .svc-config-pre .hljs-meta { color: #6a9955; }
.svc-config-pre .hljs-attr, .svc-config-pre .hljs-attribute { color: #9cdcfe; }
.svc-config-pre .hljs-string { color: #ce9178; }
.svc-config-pre .hljs-number, .svc-config-pre .hljs-literal { color: #b5cea8; }
.svc-config-pre .hljs-bullet, .svc-config-pre .hljs-section { color: #569cd6; }
.svc-config-pre .hljs-title { color: #dcdcaa; }
.svc-search-mark { background: #e6a23c; color: #1e1e1e; border-radius: 2px; padding: 0 1px; }
.svc-search-mark.svc-search-active { background: #f56c6c; color: #fff; outline: 1px solid #ff8a8a; }
/* Nacos 配置弹窗全屏：覆盖弹窗固定 80vh 高度，铺满窗口 */
.svc-config-dialog.el-dialog--fullscreen { height: 100vh; max-width: none; margin: 0; }
.svc-config-dialog.el-dialog--fullscreen .el-dialog__body { padding: 12px 24px; }
/* 配置不存在空状态 */
.svc-cfg-empty {
  flex: 1; min-height: 300px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: #fafafa; border: 1px dashed #dcdfe6; border-radius: 6px;
}
/* 编辑模式：透明 textarea 叠在高亮层上，输入即实时语法高亮 */
.svc-editor-wrap { position: relative; flex: 1; min-height: 0; }
/* 单滚动体架构：textarea 唯一滚动体，高亮层 overflow:hidden 只做视口裁剪，
   滚动跟随由 canvas transform 平移完成——scrollTop 赋值会被 clamp 导致两层失步，
   transform 平移数学精确，从根上消除重影/光标错行 */
.svc-editor-wrap .svc-editor-pre { position: absolute; inset: 0; overflow: hidden; }
.svc-editor-canvas { display: block; position: relative; will-change: transform; }
.svc-editor-textarea {
  position: absolute; inset: 0; width: 100%; height: 100%;
  padding: 12px 14px; margin: 0; border: none; outline: none; resize: none;
  background: transparent; color: transparent; caret-color: #a8bcc0;
  font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7;
  white-space: pre; overflow: auto; box-sizing: border-box;
  overscroll-behavior: contain;   /* 滚到底后滚动不再传递给弹窗，避免视口跟动产生错位感 */
}
/* 选区：底色用比背景更沉的深蓝，浅色高亮文字在其上才清晰；
   高亮 pre 层自身选区背景置透明，避免两层叠加把文字压暗 */
/* 编辑态 textarea 滚动条：与查看区同色（宽度保持 8px，避免破坏两层滚动槽对齐） */
.svc-editor-textarea { scrollbar-color: #2f5a6b rgba(47, 90, 107, 0.18); scrollbar-width: thin; }
.svc-editor-textarea::-webkit-scrollbar { width: 8px; height: 8px; }
.svc-editor-textarea::-webkit-scrollbar-track { background: transparent; }
.svc-editor-textarea::-webkit-scrollbar-thumb { background: #2f5a6b; border: 2px solid transparent; background-clip: padding-box; border-radius: 4px; }
.svc-editor-textarea::-webkit-scrollbar-thumb:hover { background: #3f7a8f; border: 2px solid transparent; background-clip: padding-box; }
.svc-editor-textarea::selection { background: rgba(38, 79, 120, 0.92); color: transparent; }
.svc-editor-textarea::-moz-selection { background: rgba(38, 79, 120, 0.92); color: transparent; }
.svc-editor-pre ::selection, .svc-editor-pre ::-moz-selection { background: transparent; }
/* ═══ 配置弹窗右侧 Minimap 缩略图（查看/编辑通用） ═══ */
.svc-cfg-code { padding-right: 274px; }   /* 右侧为 minimap(264px) + 自绘滚动条(10px) 预留，不遮内容 */
.svc-cfg-minimap {
  position: absolute; top: 0; right: 10px; bottom: 0; width: 264px; z-index: 5;
  background: #0d3545; border-left: 1px solid #1c4a5e;
  overflow: hidden; cursor: pointer; user-select: none;
}
.svc-cfg-minimap:hover { border-left-color: #2f6a82; }
/* 布局宽 880px = 容器 264px ÷ scale 0.3，scale 后恰好铺满列宽；origin 必须左上角，否则内容以中心缩放跑偏出容器 */
.svc-cfg-minimap-pre {
  width: 880px; margin: 0; padding: 10px 8px; white-space: pre; pointer-events: none; will-change: transform;
  transform-origin: top left;
  font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7; color: #4d7482;
}
.svc-cfg-minimap-view {
  position: absolute; left: 0; right: 0; pointer-events: none;
  background: rgba(64, 158, 255, .14);
  border-top: 1px solid rgba(103, 194, 255, .6); border-bottom: 1px solid rgba(103, 194, 255, .6);
}
/* 主内容原生竖向滚动条隐藏（自绘条贴最外缘）；横向原生条保留，Firefox scrollbar-width:none 会连横向一并隐藏（Shift+滚轮仍可横滚） */
.svc-config-pre, .svc-editor-textarea { scrollbar-width: none; }
.svc-config-pre::-webkit-scrollbar:vertical, .svc-editor-textarea::-webkit-scrollbar:vertical { display: none; }
/* 自绘竖向滚动条：thumb 品牌靛蓝（同弹窗滚动条配色规范） */
.svc-cfg-scrollbar { position: absolute; top: 0; right: 0; bottom: 0; width: 10px; z-index: 6; cursor: pointer; }
.svc-cfg-scrollbar-thumb { position: absolute; left: 2px; right: 2px; background: #2f5a6b; border-radius: 4px; }
.svc-cfg-scrollbar:hover .svc-cfg-scrollbar-thumb { background: #3f7a8f; }
/* diff 折叠占位行 */
.diff-fold-cell {
  text-align: center; padding: 4px 0; font-size: 12px;
  color: #909399; background: #fafafa; border-top: 1px solid #ebeef5; border-bottom: 1px solid #ebeef5;
}

/* ═══ 环境收藏栏（按用户落库，页面专属前缀 serviceinfo-）═══ */
/* .main 可视高 = 100vh - topbar(56) - padding上下(48)；收藏栏铺满该高度，主区仍可滚动 */
/* ═══ 视口分级缩放令牌：页面内尺寸 = 基准值 × --svc-k，断点只改系数，弹窗/抽屉不进缩放体系 ═══ */
.serviceinfo-layout {
  display: flex; width: 100%; gap: calc(16px * var(--svc-k)); align-items: stretch;
  min-height: calc(100vh - 104px);
  --svc-k: 1;                                    /* 缩放系数基准（2K 及以上） */
  --svc-fs-sm: calc(12px * var(--svc-k));        /* 辅助正文 */
  --svc-fs-md: calc(13px * var(--svc-k));        /* 卡片正文 */
  --svc-fs-lg: calc(14px * var(--svc-k));        /* 卡片/收藏栏标题 */
  --svc-fs-title: calc(15px * var(--svc-k));     /* 空态主文案 */
  --svc-gap: calc(12px * var(--svc-k));          /* 卡片网格间距 */
  --svc-card-min: calc(360px * var(--svc-k));    /* 卡片列最小宽 */
  --svc-fav-w: calc(220px * var(--svc-k));       /* 收藏栏宽 */
}
@media (max-width: 1999px) { .serviceinfo-layout { --svc-k: 0.75; } }  /* 1080p 主流档 */
@media (max-width: 1365px) { .serviceinfo-layout { --svc-k: 0.65; } }  /* 小屏兜底 */
/* ═══ Element Plus 组件随 --svc-k 缩放（页面内按钮/标签/选择器；弹窗/抽屉 teleport 到 body 不受影响）═══ */
.serviceinfo-layout .el-button--small {
  height: calc(24px * var(--svc-k));
  padding: calc(5px * var(--svc-k)) calc(11px * var(--svc-k));
  font-size: calc(12px * var(--svc-k));
}
.serviceinfo-layout .el-button--small.is-link { height: auto; }
.serviceinfo-layout .el-button + .el-button { margin-left: calc(6px * var(--svc-k)); }   /* EP 相邻按钮默认 12px 间距，基准压半同步缩放 */
.serviceinfo-layout .el-tag--small {
  height: calc(20px * var(--svc-k));
  padding: 0 calc(9px * var(--svc-k));
  font-size: calc(12px * var(--svc-k));
}
.serviceinfo-layout .el-select--small .el-select__wrapper {
  min-height: calc(24px * var(--svc-k));
  font-size: calc(12px * var(--svc-k));
}
.serviceinfo-favbar {
  flex: 0 0 var(--svc-fav-w); width: var(--svc-fav-w);
  background: #fafbfc; border: 1px solid #ebeef5; border-radius: 8px;
  padding: calc(12px * var(--svc-k)); display: flex; flex-direction: column;
  transition: flex-basis .2s ease, width .2s ease, padding .2s ease;
}
.serviceinfo-favbar.collapsed { flex: 0 0 calc(44px * var(--svc-k)); width: calc(44px * var(--svc-k)); padding: calc(12px * var(--svc-k)) 6px; }
.serviceinfo-favhead { display: flex; align-items: center; justify-content: space-between; margin-bottom: calc(10px * var(--svc-k)); }
.serviceinfo-favbar.collapsed .serviceinfo-favhead { justify-content: center; }
.serviceinfo-favtitle { font-size: var(--svc-fs-lg); font-weight: 600; color: #303133; white-space: nowrap; }
.serviceinfo-favbar.collapsed .serviceinfo-favtitle { display: none; }
.serviceinfo-favtoggle { font-size: var(--svc-fs-lg); color: #909399; padding: 2px 4px; }
.serviceinfo-favlist { display: flex; flex-direction: column; gap: calc(8px * var(--svc-k)); flex: 1; min-height: 0; overflow-y: auto; }
.serviceinfo-favempty { color: #c0c4cc; font-size: var(--svc-fs-sm); text-align: center; padding: 24px 8px; line-height: 1.6; flex: 1; display: flex; align-items: center; justify-content: center; }
.serviceinfo-favcard {
  display: flex; align-items: center; justify-content: space-between; gap: 6px;
  background: #fff; border: 1px solid #ebeef5; border-radius: 8px;
  padding: calc(8px * var(--svc-k)) calc(10px * var(--svc-k)); cursor: pointer;
  transition: transform .15s ease, box-shadow .15s ease, border-color .15s ease;
}
.serviceinfo-favcard[draggable="true"] { cursor: grab; }
.serviceinfo-favcard:active { cursor: grabbing; }
.svc-fav-dragging { opacity: .35; }
.serviceinfo-favcard:hover { transform: translateY(-1px); box-shadow: 0 2px 8px rgba(64, 158, 255, .10); }
.serviceinfo-favcard.is-active { background: #ecf5ff; }   /* 选中态：仅底色+圆圈变蓝，不加左侧蓝条（避免与 L 连线冲突） */
.serviceinfo-favmain { min-width: 0; flex: 1; }
.serviceinfo-favproj { font-weight: 600; font-size: var(--svc-fs-md); color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.serviceinfo-favenv { font-size: var(--svc-fs-sm); color: #909399; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.serviceinfo-favdot { color: #c0c4cc; margin-right: 4px; }
.serviceinfo-favcard.is-active .serviceinfo-favdot { color: #409eff; }
.serviceinfo-favdel { color: #c0c4cc; opacity: 0; transition: opacity .15s, color .15s; flex-shrink: 0; padding: 2px 4px; }
.serviceinfo-favcard:hover .serviceinfo-favdel { opacity: 1; color: #f56c6c; }
/* 收藏按项目父归纳：组头 RAL 5022 夜蓝（rgb(34,45,90)）色框（仅展示+整组拖拽），子项 L 形树状连线挂接 */
.serviceinfo-favgroup { display: flex; flex-direction: column; gap: calc(6px * var(--svc-k)); }
.serviceinfo-favgroup + .serviceinfo-favgroup { margin-top: calc(10px * var(--svc-k)); padding-top: calc(10px * var(--svc-k)); border-top: 1px dashed #ebeef5; }
.serviceinfo-favgroup-head {
  display: flex; align-items: center; gap: 5px;
  background: linear-gradient(135deg, #2c3870, #222d5a);
  border: 1px solid #3d4a88; border-left: 3px solid #7488cc;
  border-radius: 6px; padding: calc(5px * var(--svc-k)) calc(8px * var(--svc-k));
  font-size: var(--svc-fs-md); color: #ccd7f4;
  cursor: grab; user-select: none;
}
.serviceinfo-favgroup-head:active { cursor: grabbing; }
.serviceinfo-favgroup-icon { color: #8ea6dd; font-size: 10px; line-height: 1; }
.serviceinfo-favgroup-name { font-weight: 700; letter-spacing: .3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.serviceinfo-favgroup-cnt { margin-left: auto; font-size: var(--svc-fs-sm); color: #ccd7f4; background: rgba(255, 255, 255, .14); border-radius: 8px; padding: 0 6px; line-height: 1.6; }
/* L 形连线：竖线自组头底沿引下（top 跨过组间距），每卡一条横线 └ 挂接；末端收在最后卡中线 */
.serviceinfo-favgroup-items { position: relative; display: flex; flex-direction: column; gap: calc(6px * var(--svc-k)); padding-left: 12px; }
.serviceinfo-favgroup-items::before {
  content: ''; position: absolute; left: 5px; top: calc(-6px * var(--svc-k)); bottom: 24px;
  width: 1px; background: #c6e2ff;
}
.serviceinfo-favcard { position: relative; }
.serviceinfo-favcard::before {
  content: ''; position: absolute; left: -7px; top: 50%; margin-top: -1px;
  width: 7px; height: 2px; background: #c6e2ff; border-radius: 1px;
}
.serviceinfo-main { flex: 1; min-width: 0; }

/* ═══ 日志目录弹窗 ═══ */
.svc-logfile-name { cursor: pointer; transition: color .15s; }
.svc-logfile-name:hover { color: #409eff; text-decoration: underline; }
.svc-logfile-name.is-running { color: #67c23a; font-weight: 600; }
.svc-logfile-name.is-running:hover { color: #85ce61; }
.svc-logfile-name.is-disabled { cursor: not-allowed; color: #5c6b70; text-decoration: none; }
.svc-logfile-name.is-disabled:hover { color: #5c6b70; text-decoration: none; }
.lf-view-disabled { color: #a8abb2 !important; cursor: not-allowed !important; }
/* 内容查看弹窗暗色主题（与运行日志弹窗风格一致） */
.svc-logfile-dialog { --el-dialog-bg-color: #0a2e3c; }
.svc-logfile-dialog .el-dialog { background: #0a2e3c !important; }
.svc-logfile-dialog .el-dialog__header { background: #0a2e3c !important; border-bottom: 1px solid #1c4a5e; }
.svc-logfile-dialog .el-dialog__title { color: #a8bcc0 !important; }
.svc-logfile-dialog .el-dialog__headerbtn .el-dialog__close { color: #7fa3ad; }
.svc-logfile-dialog .el-dialog__headerbtn .el-dialog__close:hover { color: #d4e6ea; }
.svc-logfile-dialog .el-dialog__body { background: #0a2e3c !important; padding: 12px; }
.svc-logfile-dialog .el-dialog__footer { background: #0a2e3c !important; }
.svc-logfile-dialog .el-input__wrapper { background: #0f3a4c; box-shadow: 0 0 0 1px #1c4a5e inset; }
.svc-logfile-dialog .el-input__inner { color: #a8bcc0; }
.svc-logfile-dialog .el-input__inner::placeholder { color: #4d6d78; }
/* 搜索定位按钮深色（与运行日志弹窗一致，含无匹配时 disabled 态） */
.svc-logfile-dialog .el-button {
  background: #0f3a4c; border-color: #1c4a5e; color: #a8bcc0;
}
.svc-logfile-dialog .el-button:hover:not(:disabled) { background: #14465c; border-color: #2f5a6b; color: #d4e6ea; }
.svc-logfile-dialog .el-button:disabled { background: #0c3140; border-color: #164052; color: #4d6d78; }
.svc-logfile-pre {
  height: 70vh; overflow: auto; margin: 0; padding: 12px 14px;
  background: #0a2e3c; color: #a8bcc0; border-radius: 6px;
  font-family: Consolas, Menlo, monospace; font-size: 12.5px; line-height: 1.7;
  white-space: pre-wrap; word-break: break-all; min-height: 120px;
  scrollbar-color: #2f5a6b #0a2e3c; scrollbar-width: thin;
}
.svc-logfile-pre { --sb-thumb: #2f5a6b; --sb-thumb-hover: #3f7a8f; --sb-track: #0a2e3c; }
/* 搜索定位当前行：比行内 <mark> 更明显的行级高亮 */
.lf-cur-match { background: rgba(230, 162, 60, 0.18); box-shadow: inset 3px 0 0 #e6a23c; }
`;

  document.head.appendChild(style);
})();
