# API - Nginx

> 认证方式与通用响应见 [API文档.md](API文档.md)。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/nginx/list` | 配置列表（文件名/MD5/同步时间） |
| GET | `/api/nginx/file/<id>` | 配置内容 |
| POST | `/api/nginx/sync` | 本地/远程同步（MD5 + 增量） |
| POST | `/api/nginx/push/<id>` | 推送并 reload 远程 Nginx |
