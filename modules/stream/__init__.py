# -*- coding: utf-8 -*-
"""
SSE 多路复用：GET /api/stream?topics=a,b,c

浏览器对同一域名（HTTP/1.1）只允许 6 条并发连接，而平台页面上挂着多条常驻 SSE
（首页监控 / 服务列表 / 构建状态 / 日志流）。多开几个标签页后配额即被占满：
新页签的 SSE 永远排不上队（一直「检测中」），老连接被挤断则报
ERR_INCOMPLETE_CHUNKED_ENCODING。

多路复用后每个标签页只占 1 条连接：后端按 topics 参数为每个主题起一个泵线程，
把各主题的 payload 帧汇入共享队列，统一以 {"topic": ..., ...payload} 帧下发。
"""
