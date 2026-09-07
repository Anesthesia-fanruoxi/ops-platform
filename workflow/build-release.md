# Docker 镜像构建发布流程

> 触发方式：用户说「build 新 tag」时按本流程执行；镜像仓库 `hub.hzbxhd.com/middleware/ops-platform`

## 构建流程（固定顺序）

1. **提交推送代码**（构建前必须）
   - `git add <具体目录>`（modules static templates 等，禁用 `git add -A`，根目录 nul 是 Windows 残留垃圾勿提交）
   - commit（中文描述本轮改动）→ push
2. **版本递增**：读下方「镜像记录表」最新版本，小版本 +1（如 1.18 → 1.19；主版本变更需用户明确指定）
3. **构建镜像**
   ```
   docker build -t hub.hzbxhd.com/middleware/ops-platform:{新tag} .
   ```
   - 基础镜像 python:3.9-slim；未改 Dockerfile 时基础层/apt/pip 层全部命中缓存，仅 COPY 层重建，约几秒完成
4. **推送镜像**
   ```
   docker push hub.hzbxhd.com/middleware/ops-platform:{新tag}
   ```
5. **回填记录**：将新版本追加到下方记录表（版本 / 日期 / 变更摘要 / commit / digest）
6. **清理旧镜像**：删除镜像仓库中超出最近 3 个版本的旧 tag 及残留本体（以记录表版本序为依据，保留最新 3 个），通过 Harbor API 删除
7. **清理本机历史镜像**：本机不保留历史版本（已推送 Harbor），`docker rmi` 删除除最新 tag 外的本机 ops-platform 镜像，`docker image prune -f` 清理悬空层

## 镜像仓库清理（Harbor API）

凭据取本机 docker 登录态（`~/.docker/config.json`；`credsStore=desktop` 时经 `docker-credential-desktop get` 获取，不外泄）：

```
# 列出全部 artifact（含无 tag 的）
GET    {harbor}/api/v2.0/projects/middleware/repositories/ops-platform/artifacts?with_tag=true&page_size=100
# 删除指定 tag（仅删标签引用）
DELETE {harbor}/api/v2.0/projects/middleware/repositories/ops-platform/artifacts/{digest}/tags/{tag}
# 删除 artifact 本体（删 tag 后残留的 untagged 项需再删本体，界面才真正消失）
DELETE {harbor}/api/v2.0/projects/middleware/repositories/ops-platform/artifacts/{digest}
```

实施要点：
- 保留有 tag 的最新 3 个 artifact，其余逐个先删 tag、再删 artifact 本体（否则界面 Tags 列出现空行残留）
- 删 tag 后紧跟删本体可能 404（Harbor 内部状态异步传播），等待几十秒后轮询重试即可全部成功
- 若 tag 被设为不可变（immutable）删除失败则报告用户处理

## 镜像记录表

| 版本 | 日期 | 变更摘要 | commit | 镜像 digest |
|------|------|----------|--------|-------------|
| 1.3 | — | —（历史版本，未在本表记录） | 7a3691d | ffa08a21（短 digest） |
| 1.13 | — | —（历史版本，未在本表记录） | — | — |
| 1.14 | — | —（历史版本，未在本表记录） | — | — |
| 1.16 | — | —（历史版本，未在本表记录） | — | — |
| 1.17 | — | —（历史版本，未在本表记录） | — | — |
| 1.18 | 2026-09-03 | 服务信息页拆分 12 个 serviceinfo/ 模块（mixin 架构）；Nacos 编辑器单滚动体 transform 同步；发布对比 LCS 死循环修复；日志目录搜索定位与深色样式统一 | 2ab724b | sha256:f6a4312e42317d278590f4c0feae06a562776ce6aa1dc8b733e9a0d51f612ce2 |
| 1.19 | 2026-09-07 | 1080p 缩放体系；Nacos/ConfigMap 入口环境级判定与 ConfigMap 编辑保存；收藏父归纳分组与拖拽排序；配置弹窗 Minimap 缩略图与自绘滚动条；新增本流程文档并新增第6步旧 tag 清理 | a4e38ba | sha256:b2524a8e93c93f7db4bfb704f6ca3b1fb6642af95b23df6a9fcc088d64297cc8 |
| 1.20 | 2026-09-07 | 撤回 1080p 缩放；服务信息页工具栏下内容框滚动与卡片布局优化；环境信息页构建状态接入全局 SSE；构建步骤状态迁移 Redis 并改造步骤 SSE 为事件驱动；修复取消推送线程 DetachedInstanceError | f5cfa05 | sha256:ab76b1b912e830c2a0912f8c4bda73ee403dc8a0077a0ce2b45130a7f8f702c5 |

> 下一版本：**1.21**（build 时自动递增并回填本表）
> 历史行中 tag 已从仓库清理（仅保留最近 3 个），行本身保留作构建历史记录
