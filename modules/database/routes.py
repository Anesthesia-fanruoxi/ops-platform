# -*- coding: utf-8 -*-
"""MySQL 工具域路由注册（排序修正 + 表结构对比同步）"""
from flask import Blueprint

database_bp = Blueprint('database', __name__)

from modules.database.api import (
    list_instances, list_databases, list_tables, list_columns,
    list_column_issues,
    fix_table_async, fix_all_tables_async, fix_columns_async, fix_database_async,
    database_stream,
    download_report,
    list_datasources, create_datasource, update_datasource,
    delete_datasource, test_datasource_connection,
    compare_structure, sync_structure_sql, sync_structure_async,
    ddl_sync_projects, ddl_sync_instances, ddl_sync_tasks_list,
    ddl_sync_create_task, ddl_sync_update_task, ddl_sync_toggle_task,
    ddl_sync_delete_task, ddl_sync_logs, ddl_sync_log_stream,
)

# 查询类
database_bp.add_url_rule('/instances', 'list_instances', list_instances, methods=['GET'])
database_bp.add_url_rule('/databases', 'list_databases', list_databases, methods=['GET'])
database_bp.add_url_rule('/tables/<database>', 'list_tables', list_tables, methods=['GET'])
database_bp.add_url_rule('/columns/<database>/<table>', 'list_columns', list_columns, methods=['GET'])
database_bp.add_url_rule('/column_issues/<database>', 'list_column_issues', list_column_issues, methods=['GET'])

# 自定义数据源 CRUD
database_bp.add_url_rule('/datasources', 'list_datasources', list_datasources, methods=['GET'])
database_bp.add_url_rule('/datasources', 'create_datasource', create_datasource, methods=['POST'])
database_bp.add_url_rule('/datasources/<int:source_id>', 'update_datasource', update_datasource, methods=['PUT'])
database_bp.add_url_rule('/datasources/<int:source_id>', 'delete_datasource', delete_datasource, methods=['DELETE'])
database_bp.add_url_rule('/datasources/test', 'test_datasource_connection', test_datasource_connection, methods=['POST'])

# 修复类（异步 SSE 实时日志）
database_bp.add_url_rule('/fix_table_async', 'fix_table_async', fix_table_async, methods=['POST'])
database_bp.add_url_rule('/fix_all_tables_async', 'fix_all_tables_async', fix_all_tables_async, methods=['POST'])
database_bp.add_url_rule('/fix_columns_async', 'fix_columns_async', fix_columns_async, methods=['POST'])
database_bp.add_url_rule('/fix_database_async', 'fix_database_async', fix_database_async, methods=['POST'])
database_bp.add_url_rule('/stream', 'database_stream', database_stream, methods=['GET'])

# 报告
database_bp.add_url_rule('/report/<database>', 'download_report', download_report, methods=['GET'])

# 表结构对比与同步
database_bp.add_url_rule('/compare_structure', 'compare_structure', compare_structure, methods=['POST'])
database_bp.add_url_rule('/sync_structure_sql', 'sync_structure_sql', sync_structure_sql, methods=['POST'])
database_bp.add_url_rule('/sync_structure_async', 'sync_structure_async', sync_structure_async, methods=['POST'])

# DDL 自动同步（binlog 监听）
database_bp.add_url_rule('/ddl-sync/projects', 'ddl_sync_projects', ddl_sync_projects, methods=['GET'])
database_bp.add_url_rule('/ddl-sync/instances', 'ddl_sync_instances', ddl_sync_instances, methods=['GET'])
database_bp.add_url_rule('/ddl-sync/tasks', 'ddl_sync_tasks_list', ddl_sync_tasks_list, methods=['GET'])
database_bp.add_url_rule('/ddl-sync/tasks', 'ddl_sync_create_task', ddl_sync_create_task, methods=['POST'])
database_bp.add_url_rule('/ddl-sync/tasks/<int:task_id>', 'ddl_sync_update_task', ddl_sync_update_task, methods=['PUT'])
database_bp.add_url_rule('/ddl-sync/tasks/<int:task_id>', 'ddl_sync_delete_task', ddl_sync_delete_task, methods=['DELETE'])
database_bp.add_url_rule('/ddl-sync/tasks/<int:task_id>/toggle', 'ddl_sync_toggle_task', ddl_sync_toggle_task, methods=['POST'])
database_bp.add_url_rule('/ddl-sync/logs', 'ddl_sync_logs', ddl_sync_logs, methods=['GET'])
database_bp.add_url_rule('/ddl-sync/logs/stream/<int:task_id>', 'ddl_sync_log_stream', ddl_sync_log_stream, methods=['GET'])


def register(app):
    """注册MySQL工具域蓝图"""
    app.register_blueprint(database_bp, url_prefix='/api/database')
