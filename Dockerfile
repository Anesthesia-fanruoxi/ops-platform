FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# git：构建弹窗拉取远程分支列表（git ls-remote）依赖；openssh-client：ssh_key 凭据走 GIT_SSH_COMMAND
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 拷贝项目代码
COPY . .

# 占位启动配置：config/config.yaml 被 .gitignore 排除不入库，但 config.py 启动强制要求存在；
# 实际连接信息由 docker-compose 环境变量覆盖（环境变量优先），占位内容不影响运行
COPY config/config.example.yaml config/config.yaml

# 数据目录（日志等）
RUN mkdir -p logs

EXPOSE 8050

# gthread worker + threads：SSE 长连接（构建日志/监控/环境构建状态）需要线程模型，
# 每条 SSE 独占 1 线程，线程数需覆盖百级用户同时开 SSE 页面的场景（线程基本阻塞在 IO，GIL 会释放）
# ⚠️ 必须 -w 1：create_app() 会启动 DDL binlog 监听等后台线程，多 worker 会重复执行
# --timeout 120：SSE 连接可能长时间保持，避免 worker 被误杀
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "256", \
     "-b", "0.0.0.0:8050", "--timeout", "120", "--graceful-timeout", "30", \
     "app:create_app()"]
