# 范围边界：构建页面卡顿优化

## In Scope
- `modules/cicd/api/build_api.py`：proxy_build_log / _stream_all_log / env_builds_stream 的连接生命周期治理
- `Dockerfile`：gunicorn `--threads` 16 → 48（仅此一行，不改 worker 数/worker 模型）
- `config/config.py`：新增 SQLALCHEMY_ENGINE_OPTIONS，DB 连接池加大到 pool_size=10 / max_overflow=20（合计 30）
- `static/js/modules/deploy/ServiceInfoPage.js`：构建抽屉日志改单连接 + 本地按标记切分 + 渲染限量
- `static/js/modules/deploy/ManagePage.js`：同上（两份抽屉实现保持逻辑一致）

## Out of Scope
- 不改 Agent 端（agent/server.go 的 streamBuildLog 行为保持不变）
- 不做 gunicorn worker 模型变更（如 gevent/异步化），仅调 threads 数值
- 不抽取公共前端组件（两份抽屉仅同步逻辑）
- 不动服务卡片 stream、Pod 日志 stream、SchedulePage 监控流（仅治理构建相关流）
- 不改 DB 轮询频率以外的 steps/stream 逻辑

## 涉及对象
| 文件 | 改动类型 |
| --- | --- |
| modules/cicd/api/build_api.py | 后端：连接释放、pump 退出、env 流自动关闭 |
| Dockerfile | 配置：gunicorn threads 16 → 48 |
| config/config.py | 配置：DB 连接池 15 → 30 |
| static/js/modules/deploy/ServiceInfoPage.js | 前端：日志单连接本地切分 |
| static/js/modules/deploy/ManagePage.js | 前端：同上 |

## 变更记录
| 日期 | 变更内容 | 原因 |
| --- | --- | --- |
| 2026-08-14 | 初始范围确定 | 定位到线程耗尽（Q1）与切换全量重传（Q2）两类根因 |
| 2026-08-14 | scope 扩展：Dockerfile threads 16→48 + config.py DB 连接池 15→30 | 用户确认纳入线程池调优；作为治标加固与阶段一生命周期治理配套（线程加大必须同步加 DB 池，否则瓶颈转移到 DB 连接等待） |
