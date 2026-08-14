# -*- coding: utf-8 -*-
"""MySQL 库结构对比与同步 SQL 生成

对比维度（源库 → 目标库 单向）：
- 表：目标缺失（可建表同步）/ 目标多余（仅展示，不删除）
- 字段：缺失（ADD，按源库顺序定位）/ 定义不一致（MODIFY）/ 多余（仅展示，不删除）
- 索引：缺失（ADD）/ 定义不一致（DROP+ADD）/ 多余（仅展示，不删除）；
  主键差异仅提示不生成 SQL，全文/空间索引仅提示不生成 SQL
- 表选项：引擎 / 排序规则 / 注释（ALTER TABLE 修改）
- 视图：缺失（CREATE VIEW）/ 定义不一致（CREATE OR REPLACE VIEW）/ 多余（仅展示）
- 事件：缺失（CREATE EVENT）/ 定义不一致（DROP+CREATE EVENT）/ 多余（仅展示）

差异按「新建 / 修改 / 删除」三类归组；安全约定：所有「目标多余」对象一律不做删除操作，仅提示。
"""
from collections import OrderedDict

# 主键索引名
PRIMARY_INDEX = 'PRIMARY'
# 不参与自动生成 SQL 的索引类型（仅提示）
SKIP_INDEX_TYPES = ('FULLTEXT', 'SPATIAL')

# 字段属性对比项 → 中文标签
COLUMN_COMPARE_FIELDS = [
    ('COLUMN_TYPE', '类型'),
    ('CHARACTER_SET_NAME', '字符集'),
    ('COLLATION_NAME', '排序规则'),
    ('IS_NULLABLE', '可空'),
    ('COLUMN_DEFAULT', '默认值'),
    ('EXTRA', '扩展'),
    ('COLUMN_COMMENT', '注释'),
]


def _sql_quote(s):
    """SQL 字符串字面量转义"""
    return "'" + str(s).replace('\\', '\\\\').replace("'", "\\'") + "'"


def _norm(v):
    """展示用归一化：None → '-'"""
    return v if v not in (None, '') else '-'


def _extra_clean(extra):
    """剥离 EXTRA 中的 DEFAULT_GENERED 标记（默认值单独输出，该词不是合法 DDL）"""
    return ' '.join(
        tok for tok in (extra or '').split() if tok.upper() != 'DEFAULT_GENERATED'
    ).strip()


# ── 元数据抓取 ──

def fetch_schema_metadata(conn, database):
    """抓取整库结构元数据：{tables(有序), columns, indexes, db_charset, db_collation}"""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT TABLE_NAME, ENGINE, TABLE_COLLATION, TABLE_COMMENT
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY TABLE_NAME
    """, (database,))
    tables = OrderedDict()
    for row in cursor.fetchall():
        tables[row['TABLE_NAME']] = {
            'engine': (row['ENGINE'] or '').upper(),
            'collation': row['TABLE_COLLATION'] or '',
            'comment': row['TABLE_COMMENT'] or '',
        }

    cursor.execute("""
        SELECT TABLE_NAME, COLUMN_NAME, ORDINAL_POSITION, COLUMN_TYPE,
               CHARACTER_SET_NAME, COLLATION_NAME, IS_NULLABLE,
               COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """, (database,))
    columns = {}
    for row in cursor.fetchall():
        columns.setdefault(row['TABLE_NAME'], []).append(row)

    # 索引按 (表名, 索引名) 分组并保留字段顺序
    cursor.execute("""
        SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, SEQ_IN_INDEX, COLUMN_NAME,
               SUB_PART, INDEX_TYPE
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
    """, (database,))
    indexes = {}
    for row in cursor.fetchall():
        idxs = indexes.setdefault(row['TABLE_NAME'], OrderedDict())
        idx = idxs.setdefault(row['INDEX_NAME'], {
            'name': row['INDEX_NAME'],
            'unique': row['NON_UNIQUE'] == 0,
            'type': (row['INDEX_TYPE'] or 'BTREE').upper(),
            'columns': [],
        })
        idx['columns'].append({'name': row['COLUMN_NAME'], 'sub_part': row['SUB_PART']})

    cursor.execute("""
        SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME
        FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = %s
    """, (database,))
    db_info = cursor.fetchone() or {}

    # 视图定义（当前账号无权限读取定义时 VIEW_DEFINITION 为 NULL，不参与差异判定）
    cursor.execute("""
        SELECT TABLE_NAME, VIEW_DEFINITION, CHECK_OPTION, SECURITY_TYPE
        FROM information_schema.VIEWS
        WHERE TABLE_SCHEMA = %s
        ORDER BY TABLE_NAME
    """, (database,))
    views = OrderedDict()
    for row in cursor.fetchall():
        views[row['TABLE_NAME']] = row

    # 事件定义
    cursor.execute("""
        SELECT EVENT_NAME, EVENT_DEFINITION, EVENT_TYPE, EXECUTE_AT,
               INTERVAL_VALUE, INTERVAL_FIELD, STATUS, ON_COMPLETION,
               STARTS, ENDS, EVENT_COMMENT
        FROM information_schema.EVENTS
        WHERE EVENT_SCHEMA = %s
        ORDER BY EVENT_NAME
    """, (database,))
    events = OrderedDict()
    for row in cursor.fetchall():
        events[row['EVENT_NAME']] = row

    return {
        'database': database,
        'tables': tables,
        'columns': columns,
        'indexes': indexes,
        'views': views,
        'events': events,
        'db_charset': db_info.get('DEFAULT_CHARACTER_SET_NAME') or '',
        'db_collation': db_info.get('DEFAULT_COLLATION_NAME') or '',
    }


# ── 差异计算 ──

def _column_signature(col):
    """字段定义签名（用于判断是否需要 MODIFY）"""
    return (
        (col['COLUMN_TYPE'] or '').lower(),
        col['CHARACTER_SET_NAME'] or '',
        col['COLLATION_NAME'] or '',
        col['IS_NULLABLE'] or '',
        col['COLUMN_DEFAULT'],
        (col['EXTRA'] or '').lower(),
        col['COLUMN_COMMENT'] or '',
    )


def _column_changes(src_col, tgt_col):
    """逐属性对比两个字段，返回差异项列表 [{field, label, source, target}]"""
    changes = []
    for field, label in COLUMN_COMPARE_FIELDS:
        sv, tv = src_col.get(field), tgt_col.get(field)
        if field in ('COLUMN_TYPE', 'EXTRA'):
            sv, tv = (sv or '').lower(), (tv or '').lower()
        else:
            sv, tv = sv or '', tv or ''
        if sv != tv:
            changes.append({
                'field': field, 'label': label,
                'source': _norm(src_col.get(field)), 'target': _norm(tgt_col.get(field)),
            })
    return changes


def _index_signature(idx):
    """索引定义签名"""
    cols = tuple((c['name'], c['sub_part']) for c in idx['columns'])
    return (idx['unique'], idx['type'], cols)


def _index_diff(src_idxs, tgt_idxs):
    """对比一张表的索引，返回 {'add':[], 'modify':[], 'extra':[], 'primary_diff':None|{}}"""
    add, modify, extra = [], [], []
    primary_diff = None

    for name, sidx in src_idxs.items():
        tidx = tgt_idxs.get(name)
        if name == PRIMARY_INDEX:
            if tidx is None or _index_signature(sidx) != _index_signature(tidx):
                primary_diff = {
                    'source': _format_index_brief(sidx),
                    'target': _format_index_brief(tidx) if tidx else '无',
                }
            continue
        if tidx is None:
            add.append(sidx)
        elif _index_signature(sidx) != _index_signature(tidx):
            modify.append({'source': sidx, 'target': tidx})

    for name, tidx in tgt_idxs.items():
        if name != PRIMARY_INDEX and name not in src_idxs:
            extra.append(tidx)

    return {'add': add, 'modify': modify, 'extra': extra, 'primary_diff': primary_diff}


def _format_index_brief(idx):
    """索引简要描述（展示用）"""
    if not idx:
        return '无'
    cols = ','.join(
        f"{c['name']}({c['sub_part']})" if c['sub_part'] else c['name']
        for c in idx['columns']
    )
    kind = 'UNIQUE ' if idx['unique'] else ''
    return f"{kind}{idx['name']}({cols})"


# ── 视图 / 事件对比 ──

_EVENT_COMPARE_FIELDS = [
    ('EVENT_DEFINITION', '事件体'),
    ('EVENT_TYPE', '触发类型'),
    ('INTERVAL_VALUE', '间隔值'),
    ('INTERVAL_FIELD', '间隔单位'),
    ('EXECUTE_AT', '执行时间'),
    ('STARTS', '开始时间'),
    ('ENDS', '结束时间'),
    ('STATUS', '状态'),
    ('ON_COMPLETION', '完成后保留'),
    ('EVENT_COMMENT', '注释'),
]


def _event_signature(ev):
    """事件定义签名（忽略 DEFINER，避免不同账号造成伪差异）"""
    return tuple(str(ev.get(f) or '').strip() for f, _ in _EVENT_COMPARE_FIELDS)


def _event_changes(src_ev, tgt_ev):
    """逐属性对比两个事件，返回差异项列表 [{label, source, target}]"""
    changes = []
    for field, label in _EVENT_COMPARE_FIELDS:
        sv = str(src_ev.get(field) or '').strip()
        tv = str(tgt_ev.get(field) or '').strip()
        if sv != tv:
            changes.append({'field': field, 'label': label,
                            'source': _norm(src_ev.get(field)),
                            'target': _norm(tgt_ev.get(field))})
    return changes


def _view_signature(v):
    """视图定义签名（定义不可读时返回 None，不参与差异判定）"""
    definition = v.get('VIEW_DEFINITION')
    if definition is None:
        return None
    return (' '.join(definition.split()), v.get('CHECK_OPTION') or '',
            v.get('SECURITY_TYPE') or '')


def _view_changes(src_v, tgt_v):
    """视图差异项列表"""
    changes = []
    if ' '.join((src_v.get('VIEW_DEFINITION') or '').split()) != \
            ' '.join((tgt_v.get('VIEW_DEFINITION') or '').split()):
        changes.append({'label': '定义', 'source': '不一致', 'target': '不一致'})
    for field, label in (('CHECK_OPTION', 'CHECK 选项'), ('SECURITY_TYPE', '安全类型')):
        sv, tv = src_v.get(field) or '', tgt_v.get(field) or ''
        if sv != tv:
            changes.append({'label': label, 'source': _norm(sv), 'target': _norm(tv)})
    return changes


def _event_schedule_brief(ev):
    """事件调度简要描述（展示用）"""
    if ev.get('EVENT_TYPE') == 'ONE TIME':
        return f"AT {ev.get('EXECUTE_AT')}"
    return (f"EVERY {ev.get('INTERVAL_VALUE')} {ev.get('INTERVAL_FIELD')}"
            f" | {'启用' if ev.get('STATUS') == 'ENABLED' else '停用'}")


def build_view_sql(name, view, replace=False):
    """生成 CREATE [OR REPLACE] VIEW 语句（不携带 DEFINER，避免目标账号权限不足）"""
    keyword = 'CREATE OR REPLACE' if replace else 'CREATE'
    algorithm = view.get('ALGORITHM') or 'UNDEFINED'
    security = view.get('SECURITY_TYPE') or 'DEFINER'
    check = view.get('CHECK_OPTION')
    tail = f' WITH {check} CHECK OPTION' if check and check.upper() != 'NONE' else ''
    return (f"{keyword} ALGORITHM = {algorithm} VIEW `{name}` AS "
            f"{view['VIEW_DEFINITION'].strip()} SQL SECURITY {security}{tail}")


def build_event_sql(name, ev):
    """生成 CREATE EVENT 语句（不携带 DEFINER，避免目标账号权限不足）"""
    if ev.get('EVENT_TYPE') == 'ONE TIME':
        schedule = f"ON SCHEDULE AT '{ev['EXECUTE_AT']}'"
    else:
        schedule = f"ON SCHEDULE EVERY {ev['INTERVAL_VALUE']} {ev['INTERVAL_FIELD']}"
        if ev.get('STARTS'):
            schedule += f" STARTS '{ev['STARTS']}'"
        if ev.get('ENDS'):
            schedule += f" ENDS '{ev['ENDS']}'"
    completion = 'PRESERVE' if ev.get('ON_COMPLETION') == 'PRESERVE' else 'NOT PRESERVE'
    parts = [f"CREATE EVENT `{name}`", schedule, f"ON COMPLETION {completion}",
             'ENABLE' if ev.get('STATUS') == 'ENABLED' else 'DISABLE']
    if ev.get('EVENT_COMMENT'):
        parts.append(f"COMMENT {_sql_quote(ev['EVENT_COMMENT'])}")
    body = (ev.get('EVENT_DEFINITION') or '').strip()
    if not body.upper().startswith('DO '):
        body = f'DO {body}'
    return ' '.join(parts) + f" {body}"


def _compare_named_objects(src_meta, tgt_meta, kind, label, src_objs, tgt_objs,
                            signature_fn, changes_fn, create_sql_fn, diff_sql_fn,
                            brief_fn, summary):
    """通用对比：视图/事件等命名对象 → 缺失建、差异覆盖、多余仅提示

    签名函数返回 None 表示定义不可读，已有对象不判差异（避免伪差异）。
    """
    rows = []
    for name, src_obj in src_objs.items():
        tgt_obj = tgt_objs.get(name)
        src_sig = signature_fn(src_obj)
        if tgt_obj is None:
            summary['missing'] += 1
            rows.append({
                'object_type': label, 'table': name, 'status': 'missing',
                'engine': '-', 'comment': '', 'column_count': None,
                'ops': {'create': [{'object': label, 'name': name,
                                    'desc': brief_fn(src_obj)}],
                        'modify': [], 'drop': []},
                'sql': create_sql_fn(name, src_obj),
            })
        else:
            tgt_sig = signature_fn(tgt_obj)
            if src_sig is not None and tgt_sig is not None and src_sig != tgt_sig:
                summary['diff'] += 1
                changes = changes_fn(src_obj, tgt_obj)
                rows.append({
                    'object_type': label, 'table': name, 'status': 'diff',
                    'engine': '-', 'comment': '', 'column_count': None,
                    'ops': {'create': [],
                            'modify': [{'object': label, 'name': name,
                                        'desc': '、'.join(ch['label'] for ch in changes)}],
                            'drop': []},
                    'sql': diff_sql_fn(name, src_obj),
                })
            else:
                summary['identical'] += 1
                rows.append({
                    'object_type': label, 'table': name, 'status': 'identical',
                    'engine': '-', 'comment': '', 'column_count': None,
                    'ops': {'create': [], 'modify': [], 'drop': []},
                    'sql': None,
                })
    for name in tgt_objs:
        if name not in src_objs:
            summary['extra'] += 1
            rows.append({
                'object_type': label, 'table': name, 'status': 'extra',
                'engine': '-', 'comment': '', 'column_count': None,
                'ops': {'create': [], 'modify': [],
                        'drop': [{'object': label, 'name': name, 'executable': False}]},
                'sql': None,
            })
    return rows


def compare_schemas(src_meta, tgt_meta):
    """对比两个库的元数据（表/视图/事件），返回逐对象差异结果与汇总"""
    result_tables = []
    summary = {'total_source': len(src_meta['tables']) + len(src_meta.get('views', {}))
               + len(src_meta.get('events', {})),
               'missing': 0, 'diff': 0, 'identical': 0, 'extra': 0}

    for name, src_tbl in src_meta['tables'].items():
        src_cols = src_meta['columns'].get(name, [])
        src_idxs = src_meta['indexes'].get(name, OrderedDict())
        tgt_tbl = tgt_meta['tables'].get(name)

        if tgt_tbl is None:
            summary['missing'] += 1
            idx_count = len([i for i in src_idxs.values() if i['name'] != PRIMARY_INDEX])
            result_tables.append({
                'key': f'表:{name}', 'object_type': '表',
                'table': name, 'status': 'missing',
                'engine': src_tbl['engine'], 'comment': src_tbl['comment'],
                'column_count': len(src_cols),
                'columns_add': [c['COLUMN_NAME'] for c in src_cols],
                'columns_modify': [], 'columns_extra': [],
                'indexes_add': [_format_index_brief(i) for i in src_idxs.values()
                                if i['name'] != PRIMARY_INDEX],
                'indexes_modify': [], 'indexes_extra': [],
                'primary_diff': None, 'option_changes': [],
                'ops': {
                    'create': [{'object': '表', 'name': name,
                                'desc': f'{len(src_cols)} 字段 · {idx_count} 索引'}],
                    'modify': [], 'drop': [],
                },
                'sql': build_table_sql(name, src_tbl, src_cols, src_idxs),
            })
            continue

        tgt_cols = {c['COLUMN_NAME']: c for c in tgt_meta['columns'].get(name, [])}
        tgt_idxs = tgt_meta['indexes'].get(name, OrderedDict())

        # 字段差异（按源库顺序，ADD 携带定位信息）
        columns_add, columns_modify = [], []
        prev_col = None
        for col in src_cols:
            cname = col['COLUMN_NAME']
            tcol = tgt_cols.get(cname)
            if tcol is None:
                columns_add.append({
                    'name': cname,
                    'definition': build_column_definition(col),
                    'position': f'FIRST' if prev_col is None else f'AFTER `{prev_col}`',
                    'detail': {k: _norm(col.get(k)) for k, _ in COLUMN_COMPARE_FIELDS},
                })
            elif _column_signature(col) != _column_signature(tcol):
                columns_modify.append({
                    'name': cname,
                    'definition': build_column_definition(col),
                    'changes': _column_changes(col, tcol),
                })
            prev_col = cname
        columns_extra = [c for c in tgt_cols if c not in {x['COLUMN_NAME'] for x in src_cols}]

        # 索引差异
        idx_diff = _index_diff(src_idxs, tgt_idxs)

        # 表选项差异
        option_changes = []
        if src_tbl['engine'] != tgt_tbl['engine']:
            option_changes.append({'label': '引擎', 'source': _norm(src_tbl['engine']),
                                   'target': _norm(tgt_tbl['engine'])})
        if src_tbl['collation'] != tgt_tbl['collation']:
            option_changes.append({'label': '排序规则', 'source': _norm(src_tbl['collation']),
                                   'target': _norm(tgt_tbl['collation'])})
        if src_tbl['comment'] != tgt_tbl['comment']:
            option_changes.append({'label': '注释', 'source': _norm(src_tbl['comment']),
                                   'target': _norm(tgt_tbl['comment'])})

        has_diff = bool(columns_add or columns_modify or idx_diff['add']
                        or idx_diff['modify'] or option_changes)
        if has_diff:
            summary['diff'] += 1
            status = 'diff'
        else:
            summary['identical'] += 1
            status = 'identical'

        # 按「新建 / 修改 / 删除」归组差异（删除类仅提示不执行，executable=False）
        ops_create = [{'object': '字段', 'name': c['name'], 'desc': c['definition']}
                      for c in columns_add]
        ops_create += [{'object': '索引', 'name': i['name'], 'desc': _format_index_brief(i),
                        'executable': i['type'] not in SKIP_INDEX_TYPES}
                       for i in idx_diff['add']]
        ops_modify = [{'object': '字段', 'name': c['name'],
                       'desc': '、'.join(ch['label'] for ch in c['changes'])}
                      for c in columns_modify]
        ops_modify += [{'object': '索引', 'name': m['source']['name'], 'desc': '重建',
                        'executable': m['source']['type'] not in SKIP_INDEX_TYPES}
                       for m in idx_diff['modify']]
        ops_modify += [{'object': '表选项', 'name': oc['label'],
                        'desc': f"{oc['target']} → {oc['source']}"}
                       for oc in option_changes]
        if idx_diff['primary_diff']:
            ops_modify.append({'object': '主键', 'name': 'PRIMARY',
                               'desc': '存在差异（高危，仅提示不同步）', 'executable': False})
        ops_drop = ([{'object': '字段', 'name': cn, 'executable': False}
                     for cn in columns_extra]
                    + [{'object': '索引', 'name': i['name'], 'executable': False}
                       for i in idx_diff['extra']])

        result_tables.append({
            'key': f'表:{name}', 'object_type': '表',
            'table': name, 'status': status,
            'engine': src_tbl['engine'], 'comment': src_tbl['comment'],
            'column_count': len(src_cols),
            'columns_add': columns_add, 'columns_modify': columns_modify,
            'columns_extra': columns_extra,
            'indexes_add': idx_diff['add'], 'indexes_modify': idx_diff['modify'],
            'indexes_extra': idx_diff['extra'], 'primary_diff': idx_diff['primary_diff'],
            'option_changes': option_changes,
            'ops': {'create': ops_create, 'modify': ops_modify, 'drop': ops_drop},
            'sql': None if status == 'identical' else build_table_sync_sqls(
                name, src_cols, columns_add, columns_modify,
                idx_diff, option_changes, src_tbl),
        })

    # 目标多余表（仅提示）
    for name in tgt_meta['tables']:
        if name not in src_meta['tables']:
            summary['extra'] += 1
            result_tables.append({
                'key': f'表:{name}', 'object_type': '表',
                'table': name, 'status': 'extra',
                'engine': tgt_meta['tables'][name]['engine'],
                'comment': tgt_meta['tables'][name]['comment'],
                'column_count': len(tgt_meta['columns'].get(name, [])),
                'columns_add': [], 'columns_modify': [], 'columns_extra': [],
                'indexes_add': [], 'indexes_modify': [], 'indexes_extra': [],
                'primary_diff': None, 'option_changes': [],
                'ops': {'create': [], 'modify': [],
                        'drop': [{'object': '表', 'name': name, 'executable': False}]},
                'sql': None,
            })

    # 视图对比（缺失 CREATE VIEW / 差异 CREATE OR REPLACE / 多余仅提示）
    result_tables += _compare_named_objects(
        src_meta, tgt_meta, 'view', '视图',
        src_meta.get('views', {}), tgt_meta.get('views', {}),
        _view_signature, _view_changes, build_view_sql,
        lambda name, v: build_view_sql(name, v, replace=True),
        lambda v: f"{len((v.get('VIEW_DEFINITION') or '').split())} 词定义",
        summary)

    # 事件对比（缺失 CREATE EVENT / 差异 DROP+CREATE / 多余仅提示）
    result_tables += _compare_named_objects(
        src_meta, tgt_meta, 'event', '事件',
        src_meta.get('events', {}), tgt_meta.get('events', {}),
        _event_signature, _event_changes, build_event_sql,
        lambda name, ev: [f"DROP EVENT IF EXISTS `{name}`", build_event_sql(name, ev)],
        _event_schedule_brief, summary)

    for row in result_tables:
        row.setdefault('key', f"{row['object_type']}:{row['table']}")
    result_tables.sort(key=lambda t: ({'missing': 0, 'diff': 1, 'identical': 2,
                                       'extra': 3}[t['status']],
                                      {'表': 0, '视图': 1, '事件': 2}[t['object_type']],
                                      t['table']))

    return {
        'tables': result_tables,
        'summary': summary,
        'source_database': src_meta['database'],
        'target_database': tgt_meta['database'],
        'source_db_collation': src_meta['db_collation'],
        'target_db_collation': tgt_meta['db_collation'],
    }


# ── DDL 生成 ──

def build_column_definition(col):
    """根据 information_schema 字段元数据拼出字段定义（用于 ADD/MODIFY COLUMN）"""
    parts = [col['COLUMN_TYPE']]
    if col['CHARACTER_SET_NAME']:
        parts.append(f"CHARACTER SET {col['CHARACTER_SET_NAME']} "
                     f"COLLATE {col['COLLATION_NAME']}")
    parts.append('NULL' if col['IS_NULLABLE'] == 'YES' else 'NOT NULL')

    default = col['COLUMN_DEFAULT']
    if default is not None:
        extra = (col['EXTRA'] or '').lower()
        if 'DEFAULT_GENERATED' in extra.upper() or (
                default.upper().startswith('CURRENT_TIMESTAMP')
                or default.startswith('(')):
            parts.append(f'DEFAULT {default}')
        else:
            parts.append(f'DEFAULT {_sql_quote(default)}')
    elif col['IS_NULLABLE'] == 'YES':
        # 可空字段显式补 DEFAULT NULL，保证新建表/新增字段与源库默认行为完全一致
        parts.append('DEFAULT NULL')

    extra = _extra_clean(col['EXTRA'])
    if extra:
        parts.append(extra)
    if col['COLUMN_COMMENT']:
        parts.append(f"COMMENT {_sql_quote(col['COLUMN_COMMENT'])}")
    return ' '.join(parts)


def _index_columns_sql(idx):
    """索引字段列表片段（含前缀长度）"""
    return ','.join(
        f"`{c['name']}`({c['sub_part']})" if c['sub_part'] else f"`{c['name']}`"
        for c in idx['columns']
    )


def build_index_add_sql(table, idx):
    """生成添加索引的 ALTER 语句（主键/全文/空间索引不生成）"""
    if idx['name'] == PRIMARY_INDEX or idx['type'] in SKIP_INDEX_TYPES:
        return None
    if idx['unique']:
        return f"ALTER TABLE `{table}` ADD UNIQUE KEY `{idx['name']}` ({_index_columns_sql(idx)})"
    return f"ALTER TABLE `{table}` ADD KEY `{idx['name']}` ({_index_columns_sql(idx)})"


def build_table_sql(name, tbl, columns, indexes):
    """生成完整建表语句（用于目标缺失表），含引擎/排序规则/注释等表选项"""
    defs = [f"  `{c['COLUMN_NAME']}` {build_column_definition(c)}" for c in columns]

    for idx in indexes.values():
        cols = _index_columns_sql(idx)
        if idx['name'] == PRIMARY_INDEX:
            defs.append(f'  PRIMARY KEY ({cols})')
        elif idx['type'] in SKIP_INDEX_TYPES:
            defs.append(f"  {idx['type']} KEY `{idx['name']}` ({cols})")
        elif idx['unique']:
            defs.append(f"  UNIQUE KEY `{idx['name']}` ({cols})")
        else:
            defs.append(f"  KEY `{idx['name']}` ({cols})")

    opts = [f"ENGINE={tbl['engine'] or 'InnoDB'}"]
    collation = tbl['collation']
    if collation:
        opts.append(f"DEFAULT CHARSET={collation.split('_')[0]} COLLATE={collation}")
    if tbl['comment']:
        opts.append(f"COMMENT={_sql_quote(tbl['comment'])}")

    return (f"CREATE TABLE `{name}` (\n"
            + ',\n'.join(defs)
            + "\n) " + ' '.join(opts))


def build_table_sync_sqls(name, src_cols, columns_add, columns_modify,
                          idx_diff, option_changes, table_meta=None):
    """生成已有表的同步 SQL 列表（字段 → 索引 → 表选项，按源库字段顺序定位 ADD）"""
    sqls = []

    # 字段：按源库顺序遍历，ADD 自动携带 AFTER 定位
    prev_col = None
    add_map = {c['name']: c for c in columns_add}
    modify_map = {c['name']: c for c in columns_modify}
    for col in src_cols:
        cname = col['COLUMN_NAME']
        if cname in add_map:
            position = 'FIRST' if prev_col is None else f'AFTER `{prev_col}`'
            sqls.append(f"ALTER TABLE `{name}` ADD COLUMN `{cname}` "
                        f"{build_column_definition(col)} {position}")
        elif cname in modify_map:
            sqls.append(f"ALTER TABLE `{name}` MODIFY COLUMN `{cname}` "
                        f"{build_column_definition(col)}")
        prev_col = cname

    # 索引：缺失直接加；不一致先删后加
    for idx in idx_diff['add']:
        sql = build_index_add_sql(name, idx)
        if sql:
            sqls.append(sql)
    for item in idx_diff['modify']:
        sidx = item['source']
        if sidx['type'] in SKIP_INDEX_TYPES:
            continue
        sqls.append(f"ALTER TABLE `{name}` DROP INDEX `{sidx['name']}`")
        sql = build_index_add_sql(name, sidx)
        if sql:
            sqls.append(sql)

    # 表选项
    if option_changes and table_meta is not None:
        opt_parts = []
        for oc in option_changes:
            if oc['label'] == '引擎':
                opt_parts.append(f"ENGINE={table_meta['engine']}")
            elif oc['label'] == '排序规则':
                collation = table_meta['collation']
                charset = collation.split('_')[0] if collation else 'utf8mb4'
                opt_parts.append(f"DEFAULT CHARSET={charset} COLLATE={collation}")
            elif oc['label'] == '注释':
                opt_parts.append(f"COMMENT={_sql_quote(table_meta['comment'])}")
        if opt_parts:
            sqls.append(f"ALTER TABLE `{name}` " + ' '.join(opt_parts))

    return sqls


def build_sync_plan_sql(compare_result):
    """按对比结果生成整体同步 SQL 文本（SQL 预览用，含表/视图/事件）"""
    chunks = []
    for t in compare_result['tables']:
        kind = t.get('object_type', '表')
        if t['status'] == 'missing':
            sqls = t['sql'] if isinstance(t['sql'], list) else [t['sql']]
            chunks.append(f"-- ── 新建{kind} {t['table']} ──\n" + ';\n'.join(sqls) + ';')
        elif t['status'] == 'diff' and t['sql']:
            sqls = t['sql'] if isinstance(t['sql'], list) else [t['sql']]
            chunks.append(f"-- ── 变更{kind} {t['table']} ──\n" + ';\n'.join(sqls) + ';')
    if not chunks:
        return '-- 两侧结构一致，无需同步'
    return '\n\n'.join(chunks)
