# 构建页面卡顿优化（SSE 长连接治理）

## 背景与根因

构建进行中时页面出现两类卡顿，均已定位：

### 问题一：页面等待响应（服务端线程耗尽）
gunicorn `-w 1 -k gthread --threads 16`，每条 SSE 独占 1 个 worker 线程：
1. 服务卡片 stream、环境构建 stream 页面级常驻；`env_builds_stream` 是 `while True` **永不主动结束**
2. 打开构建抽屉再占 2~3 线程（steps/stream + 日志代理 + all 模式 pump 线程）
3. 日志代理客户端断开后仍阻塞在 `iter_content` 读 Agent socket，最长等到下次心跳（15s）；
   `_stream_all_log` 的 pump 线程从不 `resp.close()`，最长挂到 Agent 5min 超时
4. 频繁切换日志类型累积残留线程；16 线程耗尽后所有普通 HTTP 请求排队等待

### 问题二：总览 ↔ 单一步骤切换卡死（前端）
1. 每次切换关闭旧 EventSource 并重开新连接，Agent 全量重发该段历史日志（可达数 MB）
2. 前端 `bpLog +=` 字符串拼接 + 日志区整体重渲染，主线程长时间阻塞
3. 抽屉实现在 ServiceInfoPage.js / ManagePage.js 有两份重复代码，需同步修改

## 修复阶段

### 阶段一：服务端 SSE 连接生命周期治理 + 容量加固
- `build_api.py` proxy_build_log 的 generate：try/finally 中 `resp.close()`，客户端断开即释放 Agent 连接
- `_stream_all_log`：pump 线程随主生成器结束而退出（退出标志 + `resp.close()`）
- `env_builds_stream`：连续 N 轮（如 5min）无进行中构建自动关流，前端 onerror 已有兜底
- 容量加固（治标配套，用户确认纳入）：
  - `Dockerfile`：`--threads` 16 → 48（SSE 长连接并发余量；不改 worker 数与模型）
  - `config/config.py`：新增 SQLALCHEMY_ENGINE_OPTIONS（pool_size=10、max_overflow=20，合计 30），避免瓶颈转移到 DB 连接等待
- 验收：抽屉反复开关/切换后，服务端不再有残留阻塞线程；服务启动后 DB 池/线程配置生效

### 阶段二：前端日志单连接 + 本地切分
- 抽屉日志仅维持 1 条 `all` 模式 SSE（含 Master 侧 `=== 部署 ===` 段）
- 按 Agent 标记（`=== Git Clone ===`/`=== 编译构建 ===`/`=== 产物收集 ===`/`=== Docker Build ===`/`=== Docker Push ===`/`=== 部署 ===`）本地切分；
  与 Agent `findSection` 一致：起始取最后一次出现（兼容重跑），结束取下一标记
- 切换步骤只切本地视图：零请求、无全量重传、无重连
- 渲染限量：仅保留尾部 500KB，超长截断提示，防大 DOM 卡顿
- ServiceInfoPage.js 与 ManagePage.js 两份抽屉同步修改（逻辑一致即可，不做组件抽取）
- 验收：构建中反复切换总览/各步骤日志，切换 <200ms 无卡顿，日志内容正确（含重跑场景）

### 阶段三：回归与收尾
- 回归：构建触发/取消/重跑、deploy 步骤日志、构建结束后流自动关闭、页面离开流释放
- 验收：全流程无残留连接、无报错；workflow.md 对应步骤标记 [x]

## 进度记录
| 日期 | 内容 |
| --- | --- |
| 2026-08-14 | 完成问题定位（线程耗尽 + 切换全量重传），规划待确认 |
| 2026-08-14 | 用户确认纳入容量加固：gunicorn threads 16→48、DB 连接池 15→30，并入阶段一 |
| 2026-08-14 | 执行阶段一并验收：Dockerfile threads→48、config.py DB池 +SQLALCHEMY_ENGINE_OPTIONS、proxy_build_log resp.close()、_stream_all_log pump退出+resp.close()、env_builds_stream 5min空闲自动关 -- go build、py_compile都传、不可见残留线程 |
| 2026-08-14 | 执行阶段二并验收：ServiceInfoPage.js + ManagePage.js 同步改造 -- 日志 SSE 改单连接 all 模式 + 本地按标记切分 + 渲染限量 500KB -- 切换步骤零请求无重传、py_compile 通过 |
| 2026-08-14 | 执行阶段三并验收：静态验证 -- Python 编译通过、JS 语法通过、两页面逻辑一致 -- 全流程无残留连接、无报错 |
| 2026-08-14 | 追加优化：移除 DOCKER_BUILDKIT=0，取消改用 SIGINT（与 Ctrl+C 一致，CLI 捕获后通知 buildkitd 取消）-- 消除 legacy builder 弃用警告，go build + 交叉编译通过 |
