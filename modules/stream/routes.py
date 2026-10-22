# -*- coding: utf-8 -*-
"""SSE 多路复用路由注册"""
from flask import Blueprint

from modules.stream.mux_api import mux_stream

stream_bp = Blueprint('stream', __name__)
stream_bp.add_url_rule('/stream', 'mux_stream', mux_stream, methods=['GET'])


def register(app):
    app.register_blueprint(stream_bp, url_prefix='/api')
