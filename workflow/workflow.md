# 长任务工作流

> 通用规则在上，任务列表在下；每个任务的详细规划与边界见各自目录的 spec.md / scope.md。
> 流程：步骤完成 → 按验收标准验收 → 标记 [x]。

## 通用规则

1. 代码文件单个不超过 300 行，超出须拆分（文档除外）
2. 长任务流程：先在任务目录写 spec.md + scope.md → 用户确认后开始执行 → 各步骤依次执行不再逐步确认 → 每步完成后验收并标记完成 → 超出 scope 时暂停询问
3. Agent 改动须编译通过（`go build`；交叉编译 `CGO_ENABLED=0 GOOS=linux GOARCH=amd64`），部署仅替换测试节点并保留旧二进制备回退
4. 红线：不动生产环境；不提交密钥凭据；不未经确认删除文件或重置数据；不改 scope 目标外的模块
5. 修改完成后总结改动内容与效果；踩坑与决策记入对应任务 spec.md 进度记录

## 任务列表

### 服务信息卡片 SSE 实时化（已完成）→ [service-info-sse/](./service-info-sse/)

- [x] 后端数据基础：实际运行镜像/app 标签/快照构建 —— 验收：HTTP 列表镜像正确 ✅
- [x] SSE 流接口：stream（快照+增量+心跳）+ envs —— 验收：滚动更新持续收到变更事件 ✅
- [x] 前端改造：卡片订阅 SSE、openEnv 改 HTTP、断连回退 —— 验收：15 卡片实时渲染 ✅
- [x] 回归验证 —— 验收：原有功能全正常 ✅

### 构建取消 + 重跑逻辑修复（待确认）→ [build-cancel-rerun/](./build-cancel-rerun/)

- [ ] Agent 取消终止能力：exec/cancel/server（DOCKER_BUILDKIT=0、docker 路径统一、异步 kill）—— 验收：go build 编译通过
- [ ] 取消意图贯通与状态保护：build.go 启动检查 CancelRequested、complete_build 防复活 —— 验收：cancelled 不被回调覆盖
- [ ] 重跑逻辑修复：禁部署步骤重跑、拦 pending 重复触发 —— 验收：两类请求被拦截且报错明确
- [ ] 编译部署与实测回归 —— 验收：三阶段取消即时终止、各步骤重跑正常
