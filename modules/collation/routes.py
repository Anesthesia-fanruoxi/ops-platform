# -*- coding: utf-8 -*-
"""MySQL排序修正域路由注册"""
from flask import Blueprint

collation_bp = Blueprint('collation', __name__)

from modules.collation.api import (
    list_instances, list_databases, list_tables, list_columns,
    list_column_issues,
    fix_table_async, fix_all_tables_async, fix_columns_async, fix_database_async,
    collation_stream,
    download_report,
    list_datasources, create_datasource, update_datasource,
    delete_datasource, test_datasource_connection,
)

# 查询类
collation_bp.add_url_rule('/instances', 'list_instances', list_instances, methods=['GET'])
collation_bp.add_url_rule('/databases', 'list_databases', list_databases, methods=['GET'])
collation_bp.add_url_rule('/tables/<database>', 'list_tables', list_tables, methods=['GET'])
collation_bp.add_url_rule('/columns/<database>/<table>', 'list_columns', list_columns, methods=['GET'])
collation_bp.add_url_rule('/column_issues/<database>', 'list_column_issues', list_column_issues, methods=['GET'])

# 自定义数据源 CRUD
collation_bp.add_url_rule('/datasources', 'list_datasources', list_datasources, methods=['GET'])
collation_bp.add_url_rule('/datasources', 'create_datasource', create_datasource, methods=['POST'])
collation_bp.add_url_rule('/datasources/<int:source_id>', 'update_datasource', update_datasource, methods=['PUT'])
collation_bp.add_url_rule('/datasources/<int:source_id>', 'delete_datasource', delete_datasource, methods=['DELETE'])
collation_bp.add_url_rule('/datasources/test', 'test_datasource_connection', test_datasource_connection, methods=['POST'])

# 修复类（异步 SSE 实时日志）
collation_bp.add_url_rule('/fix_table_async', 'fix_table_async', fix_table_async, methods=['POST'])
collation_bp.add_url_rule('/fix_all_tables_async', 'fix_all_tables_async', fix_all_tables_async, methods=['POST'])
collation_bp.add_url_rule('/fix_columns_async', 'fix_columns_async', fix_columns_async, methods=['POST'])
collation_bp.add_url_rule('/fix_database_async', 'fix_database_async', fix_database_async, methods=['POST'])
collation_bp.add_url_rule('/stream', 'collation_stream', collation_stream, methods=['GET'])

# 报告
collation_bp.add_url_rule('/report/<database>', 'download_report', download_report, methods=['GET'])


def register(app):
    """注册MySQL排序修正域蓝图"""
    app.register_blueprint(collation_bp, url_prefix='/api/collation')
