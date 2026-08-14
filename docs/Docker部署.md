# ops-platform Docker 部署

## 前置条件

- 服务器装有 Docker + Docker Compose（`docker compose version` 可用）
- 端口：默认映射 `8050`（可用环境变量 `APP_PORT` 修改）

## 快速启动

```bash
# 1. 进入项目目录
cd /opt/ops-platform

# 2. （可选）配置环境变量，不配则用默认值
#    MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD / REDIS_PASSWORD
#    SECRET_KEY / SUPER_ADMIN_USERNAME / SUPER_ADMIN_PASSWORD / APP_PORT

# 3. 构建并启动（首次会自动建 MySQL 库表、种子菜单/角色/超管）
docker compose up -d --build

# 4. 查看状态
docker compose ps
```

启动后访问：`http://服务器IP:8050`

- 超管登录（管理员标签）：`admin` / `admin123`（首次启动务必修改，或用 `SUPER_ADMIN_PASSWORD` 预置）

## 常用命令

```bash
docker compose logs -f app          # 应用日志
docker compose logs -f mysql        # 数据库日志
docker compose restart app          # 重启应用
docker compose down                 # 停止（保留数据卷）
docker compose down -v              # 停止并删除数据卷（⚠️ 清空 MySQL/Redis 数据）
docker compose pull && docker compose up -d   # 升级镜像
```

## 配置说明

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `APP_PORT` | 8050 | 宿主机映射端口 |
| `SECRET_KEY` | please-change-me | 会话加密密钥，**生产必须修改** |
| `MYSQL_ROOT_PASSWORD` | ops_root_pw | MySQL root 密码 |
| `MYSQL_PASSWORD` | ops_app_pw | 应用账号密码 |
| `REDIS_PASSWORD` | ops_redis_pw | Redis 密码 |
| `SUPER_ADMIN_USERNAME` | admin | 超管账号 |
| `SUPER_ADMIN_PASSWORD` | admin123 | 超管密码 |
| `AUTHPLATFORM_*` | - | 首次启动后在「系统设置」页面配置（存 settings 表，**不支持环境变量**） |

> 启动连接（MySQL/Redis/端口）支持环境变量覆盖且环境变量优先；其余业务配置（认证中心、Agent 通讯密钥等）在「系统设置」页面维护，详见 `config/config.py`。

## 数据持久化

- `mysql_data`：MySQL 数据卷（删容器不丢数据）
- `redis_data`：Redis 数据卷
- `app_logs`：应用日志（挂载到容器 `/app/logs`）

## 注意事项

1. **首次启动慢**：MySQL 首次初始化 + 应用建表，等 `docker compose ps` 显示 healthy 再访问
2. **SSE**：应用用 `gthread` worker + threads（Dockerfile 已配），构建日志/监控实时推送不受影响
3. **时区**：容器已设 `TZ=Asia/Shanghai`
4. **调度中心 Agent**：平台自身用 Docker 部署后，`cicd-agent` 二进制（`agent/dist/cicd-agent`）仍需按原方式部署到各构建节点（Agent 是独立 Go 程序，不在本镜像内）
5. **升级代码**：`git pull` 后 `docker compose up -d --build` 重建应用镜像即可
