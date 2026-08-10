# -*- coding: utf-8 -*-
"""
数据库全局唯一实例

所有域模型统一 `from core.db import db`，确保共享同一 SQLAlchemy 实例与 metadata。
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
