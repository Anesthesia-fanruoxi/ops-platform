FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 拷贝项目代码
COPY . .

# 数据目录（日志等）
RUN mkdir -p logs

EXPOSE 8050

# gthread worker + threads：SSE 长连接（构建日志/监控/环境构建状态）需要线程模型
# ⚠️ 必须 -w 1：create_app() 会启动 DDL binlog 监听等后台线程，多 worker 会重复执行
# --timeout 120：SSE 连接可能长时间保持，避免 worker 被误杀
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "16", \
     "-b", "0.0.0.0:8050", "--timeout", "120", "--graceful-timeout", "30", \
     "app:create_app()"]
