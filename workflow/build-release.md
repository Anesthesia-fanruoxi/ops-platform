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

## 镜像记录表

| 版本 | 日期 | 变更摘要 | commit | 镜像 digest |
|------|------|----------|--------|-------------|
| 1.3 | — | —（历史版本，未在本表记录） | 7a3691d | ffa08a21（短 digest） |
| 1.13 | — | —（历史版本，未在本表记录） | — | — |
| 1.14 | — | —（历史版本，未在本表记录） | — | — |
| 1.16 | — | —（历史版本，未在本表记录） | — | — |
| 1.17 | — | —（历史版本，未在本表记录） | — | — |
| 1.18 | 2026-09-03 | 服务信息页拆分 12 个 serviceinfo/ 模块（mixin 架构）；Nacos 编辑器单滚动体 transform 同步；发布对比 LCS 死循环修复；日志目录搜索定位与深色样式统一 | 2ab724b | sha256:f6a4312e42317d278590f4c0feae06a562776ce6aa1dc8b733e9a0d51f612ce2 |

> 下一版本：**1.19**（build 时自动递增并回填本表）
