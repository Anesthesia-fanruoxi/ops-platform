# -*- coding: utf-8 -*-
"""
构建日志服务：接收 Agent 分片追加 + SSE tail 推送（复用 collation 模式）
"""
import os
import json
import time

from flask import Response


def append_log(log_file, lines):
    """接收 Agent 日志分片，追加到日志文件"""
    if not log_file:
        return
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, 'a', encoding='utf-8') as f:
        for line in lines:
            f.write(line + '\n')


def stream_build_log(build):
    """
    SSE 流式推送构建日志（从头读取 + tail 等待新内容）
    build: Build 模型实例
    """
    log_file = build.log_file

    def generate():
        # 等待日志文件创建（最多 15s）
        if not os.path.exists(log_file):
            for _ in range(30):
                if os.path.exists(log_file):
                    break
                time.sleep(0.5)
            else:
                yield f"data: {json.dumps({'done': True, 'success': False, 'message': '日志文件未创建'})}\n\n"
                return

        with open(log_file, 'r', encoding='utf-8') as f:
            while True:
                line = f.readline()
                if line:
                    line = line.strip()
                    if line:
                        yield f"data: {json.dumps({'line': line}, ensure_ascii=False)}\n\n"
                        time.sleep(0.02)
                    continue

                # 暂无新内容：检查构建是否已终态
                from modules.cicd.models import Build
                b = Build.query.get(build.id)
                if b and b.status in ('success', 'failed', 'cancelled'):
                    yield f"data: {json.dumps({'done': True, 'success': b.status == 'success', 'status': b.status}, ensure_ascii=False)}\n\n"
                    return
                time.sleep(0.3)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'}
    )
