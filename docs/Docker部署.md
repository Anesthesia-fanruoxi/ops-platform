# ops-platform Docker 部署

## 前置条件

- 服务器装有 Docker + Docker Compose（`docker compose version` 可用）
- 服务器能访问现有 MySQL/Redis：`192.168.6.2:3306` / `192.168.6.2:6380`（可用环境变量改指向）
- 端口：默认映射 `8050`（可用环境变量 `APP_PORT` 修改）

## 快速启动

```bash
# 1. 进入项目目录
cd /opt/ops-platform

# 2. （可选）配置环境变量，不配则用默认值（默认连现有 192.168.6.2 MySQL/Redis）
#    MYSQL_HOST / MYSQL_PORT / MYSQL_DB / MYSQL_USER / MYSQL_PASS
#    REDIS_HOST / REDIS_PORT / REDIS_PASSWORD
#    SECRET_KEY / APP_PORT

# 3. 构建并启动（复用现有数据库，业务配置/账号数据直接可用）
docker compose up -d --build

# 4. 查看状态
docker compose ps
```

启动后访问：`http://服务器IP:8050`

- 超管登录（管理员标签）：`admin` / `admin123`（用现有库则沿用库内已有账号，务必修改默认密码，或用 `SUPER_ADMIN_PASSWORD` 预置）

## 常用命令

```bash
docker compose logs -f app          # 应用日志
docker compose restart app          # 重启应用
docker compose down                 # 停止（保留数据卷）
docker compose down -v              # 停止并删除数据卷（⚠️ 清空日志/产物数据）
docker compose pull && docker compose up -d   # 升级镜像
```

## 配置说明

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `APP_PORT` | 8050 | 宿主机映射端口 |
| `SECRET_KEY` | please-change-me | 会话加密密钥，**生产必须修改** |
| `MYSQL_HOST` | 192.168.6.2 | MySQL 地址（现有生产库） |
| `MYSQL_PORT` | 3306 | MySQL 端口 |
| `MYSQL_DB` | ops-platform | 数据库名 |
| `MYSQL_USER` | root | MySQL 账号 |
| `MYSQL_PASS` | root | MySQL 密码 |
| `REDIS_HOST` | 192.168.6.2 | Redis 地址 |
| `REDIS_PORT` | 6380 | Redis 端口 |
| `REDIS_PASSWORD` | redis | Redis 密码 |
| `SUPER_ADMIN_USERNAME` | admin | 超管账号（仅首次初始化） |
| `SUPER_ADMIN_PASSWORD` | admin123 | 超管密码（仅首次初始化） |

> Redis `db=1`、`key_prefix=ops:platform:` 固定与本地一致：Agent 心跳、同环境锁、认证会话依赖这些 key，改了对不上会导致构建/通讯异常。
> 其余业务配置（认证中心、Agent 通讯密钥等）在「系统设置」页面维护（settings 表），连现有库无需重配。

## 数据持久化

- `app_logs`：应用日志（挂载到容器 `/app/logs`）
- `product`：部署产物 YAML（挂载到容器 `/app/product`）
- `nginx_configs`：平台管理的 Nginx 配置
- `recycle`：回收站

> 业务数据全部在外部 MySQL（192.168.6.2），容器销毁不影响数据。

## 注意事项

1. **连接复用**：复用现有 MySQL/Redis，无中间件初始化，容器起来即可访问
2. **SSE**：应用用 `gthread` worker + threads（Dockerfile 已配），构建日志/监控实时推送不受影响
3. **时区**：容器已设 `TZ=Asia/Shanghai`
4. **调度中心 Agent**：平台自身用 Docker 部署后，`cicd-agent` 二进制（`agent/dist/cicd-agent`）仍需按原方式部署到各构建节点（Agent 是独立 Go 程序，不在本镜像内）
5. **升级代码**：`git pull` 后 `docker compose up -d --build` 重建应用镜像即可
