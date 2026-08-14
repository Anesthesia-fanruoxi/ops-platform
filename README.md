# 运维平台（ops-platform）

面向内部研发/运维的一体化运维管理平台：项目管理、环境部署、Nginx 配置管理、CI/CD 构建调度、MySQL 数据库工具（排序修复/结构对比/DDL 同步），前端为 Vue（CDN 引入）单页应用，Agent 端为 Go 编写的构建节点程序。

## 功能模块

| 模块 | 说明 |
|---|---|
| 系统管理 | 用户 / 角色 / 权限 / 登录认证 / 系统设置 |
| 部署管理 | 项目与环境、NFS/Harbor/K8s/Nacos 集成、YAML 生成与同步、环境回收 |
| Nginx 配置 | 配置模板生成、本地/远程同步、MD5 校验 |
| CI/CD | 构建流程模板、凭据管理、Agent 注册/调度、构建与自动部署、调度中心 SSE 实时看板 |
| 数据库工具 | MySQL 实例发现、排序规则校验与异步修复、表结构对比同步、binlog DDL 同步（SSE 日志） |

## 技术栈

- 后端：Python 3.9+ / Flask / Flask-SQLAlchemy
- 数据库：MySQL 8（InnoDB）
- 缓存与协调：Redis 6+（认证会话、Agent 心跳、调度概览缓存、分布式锁）
- 前端：Vue 3（CDN）+ Element Plus + Vue Router（`templates/base.html` 单页承载）
- Agent：Go 1.21（`agent/`，拉取/推送双模式，AES-GCM 加密通信）

## 目录结构

```text
ops-platform/
├── app.py                  # Flask 入口（默认端口 8050）
├── config/config.py        # 配置（环境变量可覆盖）
├── core/                   # 内核：db / bootstrap / security / response / redis_client
├── modules/
│   ├── system/             # 用户/角色/认证/设置
│   ├── deploy/             # 部署（环境/项目/NFS/Harbor/K8s/Nacos）
│   ├── nginx/              # Nginx 配置管理
│   ├── cicd/               # CI/CD（构建/Agent/调度/凭据）
│   └── database/           # MySQL 工具（排序/结构对比/DDL 同步）
├── agent/                  # Go 构建节点（cicd-agent）
├── static/                 # 前端（vue / element-plus / 页面 JS）
├── templates/              # base.html 单页模板
├── product/                # 各项目环境的 YAML 产物
├── nginx_configs/          # Nginx 配置本地存储
├── logs/                   # 构建/部署/数据库工具日志
├── docs/                   # 模块手册、设计文档、部署流程、Redis 说明
└── docker-compose.yml / Dockerfile
```

## 快速开始

### 1. 依赖

```bash
pip install -r requirements.txt
```

### 2. 依赖服务

- **MySQL**：默认连接 `root:root@192.168.6.2:3306/ops-platform`（当前在 [app.py](app.py) 中硬编码，如需更换请修改 `SQLALCHEMY_DATABASE_URI`）。首次启动会自动建表并写入种子数据（内置角色、`admin/admin123` 管理员、默认设置）。
- **Redis**：默认 `redis://:redis@192.168.6.2:6380/1`，可通过环境变量 `REDIS_URL` 覆盖。

### 3. 启动

```bash
# 开发模式
python app.py            # http://localhost:8050

# 生产模式（Docker）
docker compose up -d     # http://localhost:5000
```

默认管理员账号：`admin / admin123`（首次登录后请尽快修改）。

## 配置说明

**启动连接配置**（MySQL / Redis / 服务端口）在 [config/config.yaml](config/config.yaml) 中维护，文件缺失或解析失败时启动直接报错；MySQL、Redis 各项支持环境变量覆盖且**环境变量优先**（如 `MYSQL_HOST`、`REDIS_URL`、`REDIS_ENABLED`、`REDIS_KEY_PREFIX`），Docker 部署即通过环境变量注入连接信息。

**业务配置**（NFS / Harbor / K8s / Nginx / 中间件等）统一从 MySQL `settings` 表读取，在「系统设置」页面维护，分四个标签页：

- 部署环境（deploy）
- Nginx 配置（nginx）
- 中间件配置（middleware）
- 平台设置（platform）：Token 过期时间、密码规则、Agent 通讯密钥

> NFS / Harbor / K8s / Nginx / 中间件等业务连接参数统一从 MySQL settings 表读取，
> 不再使用环境变量/代码默认值；未配置时按空处理。

## Redis 使用说明

认证、Agent 心跳、调度概览缓存、分布式锁、登录限流均基于 Redis，键统一使用 `ops:platform:` 前缀。完整键设计见 [docs/Redis使用说明.md](docs/Redis使用说明.md)。

**认证**：登录会话只存 Redis（MySQL 无 `auth_tokens` 表），每次有效请求滑动续期（默认 8 小时，可在平台设置调整）。Redis 故障时认证不可用，所有用户需在恢复后重新登录。

**降级策略**：除认证外，Redis 故障时设置读取回源 MySQL、分布式锁降级为进程内锁、概览缓存直接计算，业务不中断。

## CI/CD Agent

Agent 为 Go 编写的独立进程（`agent/`），由 Master 通过 SSH 安装/更新。

```bash
cd agent
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o dist/cicd-agent .
```

安装入口：调度中心 → 节点 → 安装（平台会自动编译并下发 `dist/cicd-agent`）。Agent 与 Master 之间使用共享密钥（`agent_comm_secret`）做 AES-GCM 加密通信。

## 文档索引

**模块手册**

- [docs/系统管理.md](docs/系统管理.md)：认证 / SSO 接入 / 用户 / 角色 / 设置 / 审计 / 监控
- [docs/部署管理.md](docs/部署管理.md)：项目 / 环境 / 部署 / 服务信息
- [docs/Nginx配置管理.md](docs/Nginx配置管理.md)：Nginx 配置管理
- [docs/CI-CD.md](docs/CI-CD.md)：构建 / Agent / 调度 / 自动部署
- [docs/MySQL工具模块.md](docs/MySQL工具模块.md)：排序修复 / 结构对比同步 / DDL 同步

**设计文档**

- [docs/统一鉴权中心设计.md](docs/统一鉴权中心设计.md)：统一鉴权中心（SSO）设计
- [docs/authPlatform接入文档.md](docs/authPlatform接入文档.md)：鉴权中心接口接入规范
- [docs/Redis使用说明.md](docs/Redis使用说明.md)：Redis 键设计与降级策略
- [docs/UI设计文档.md](docs/UI设计文档.md)：前端设计参考

**API 参考**

- [docs/API文档.md](docs/API文档.md)：接口总览（认证方式 / 响应格式 / 错误码）
- [docs/API-系统管理.md](docs/API-系统管理.md)：认证 / 用户 / 角色 / 设置 / 审计 / 监控
- [docs/API-部署管理.md](docs/API-部署管理.md)：部署 / 环境 / Harbor / Nacos / NFS / 服务信息
- [docs/API-Nginx.md](docs/API-Nginx.md)：Nginx 配置管理
- [docs/API-CICD.md](docs/API-CICD.md)：模板 / 凭据 / Agent / 构建 / 调度
- [docs/API-数据库工具.md](docs/API-数据库工具.md)：排序修复 / 结构同步 / DDL 同步

**运维部署**

- [docs/部署流程.md](docs/部署流程.md)：环境部署与回收详细流程
- [docs/部署运维手册.md](docs/部署运维手册.md)：本地开发 / 生产部署 / 日志 / 备份

**开发规范与基础设施**

- [docs/核心与基础设施.md](docs/核心与基础设施.md)：core 内核与 config 配置体系
- [docs/Agent设计.md](docs/Agent设计.md)：Go 构建节点
- [docs/数据字典.md](docs/数据字典.md)：统一数据库表说明
- [docs/开发指南.md](docs/开发指南.md)：如何新增模块/接口、分层约定

## 注意事项

- 默认凭据（MySQL `root:root`、Redis `redis`、管理员 `admin/admin123`）仅限内网环境，生产部署请务必修改。
- `agent_comm_secret` 为只读设置，改动会导致所有 Agent 通讯失效。
- 认证依赖 Redis 且未强制持久化，Redis 重启后所有用户需重新登录（已接受的取舍）。
