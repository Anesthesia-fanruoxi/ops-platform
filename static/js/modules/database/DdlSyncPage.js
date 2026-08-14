// ============================================================
// DDL自动同步页面
// - 任务配置：选项目 → 勾选数据源（无主从，任一源变更分发到其他勾选源）→ 统一库名
// - 忽略同步：勾选后该源只发不收（自身变更仍分发，但不执行他源变更）
// - 任务随时可改，保存后监听线程自动增量对齐
// ============================================================
const { nextTick } = Vue;

const DdlSyncPage = {
  name: 'DdlSyncPage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
<div>
  <div class="toolbar" style="display:flex;gap:8px;margin-bottom:12px;">
    <el-button type="primary" v-if="canEdit" @click="openCreate">新建同步任务</el-button>
    <el-button plain @click="loadTasks">刷新</el-button>
  </div>
  <el-alert type="warning" :closable="false" style="margin-bottom:16px;">
    <template #title>
      前置要求：各数据源 MySQL 需开启 binlog，平台连接账号需具备 REPLICATION SLAVE / REPLICATION CLIENT 权限。
      任务创建后以当前 binlog 位点为基线，仅同步此后的新 DDL（全部库，系统库自动跳过）；DROP / TRUNCATE 不跟随执行，仅记录日志。
    </template>
  </el-alert>

  <el-table :data="taskRows" v-loading="loading" row-key="id" size="small" border>
    <el-table-column prop="name" label="任务名称" min-width="130"></el-table-column>
    <el-table-column prop="project" label="项目" min-width="90"></el-table-column>
    <el-table-column label="同步范围" width="170">
      <template #default>
        <span style="color:#999;">全部库（系统库自动跳过）</span>
      </template>
    </el-table-column>
    <el-table-column label="数据源" min-width="240">
      <template #default="scope">
        <el-tag v-for="s in scope.row.source_names" :key="s.id" size="small"
                :type="s.listening ? 'success' : 'info'" style="margin-right:4px;">
          [[ s.name ]][[ s.ignored ? '·忽略' : '' ]]
        </el-tag>
      </template>
    </el-table-column>
    <el-table-column label="状态" width="90" align="center">
      <template #default="scope">
        <el-tag size="small" :type="scope.row.enabled ? 'success' : 'info'">[[ scope.row.enabled ? '启用' : '停用' ]]</el-tag>
      </template>
    </el-table-column>
    <el-table-column prop="last_sync_at" label="最近同步" width="160"></el-table-column>
    <el-table-column label="操作" width="250" align="center" fixed="right">
      <template #default="scope">
        <template v-if="canEdit">
          <el-button link type="primary" size="small" @click="openEdit(scope.row)">编辑</el-button>
          <el-button link :type="scope.row.enabled ? 'warning' : 'success'" size="small"
                     @click="toggleTask(scope.row)">[[ scope.row.enabled ? '停用' : '启用' ]]</el-button>
        </template>
        <el-button link type="primary" size="small" @click="openLogs(scope.row)">日志</el-button>
        <el-popconfirm v-if="canEdit" title="删除任务后将停止对应监听，确认删除？" @confirm="deleteTask(scope.row)">
          <template #reference><el-button link type="danger" size="small">删除</el-button></template>
        </el-popconfirm>
      </template>
    </el-table-column>
  </el-table>

  <!-- 新建/编辑任务弹窗 -->
  <el-dialog v-model="formVisible" :title="form.id ? '编辑同步任务' : '新建同步任务'" width="660px" destroy-on-close>
    <el-form label-width="92px">
      <el-form-item label="任务名称" required>
        <el-input v-model="form.name" placeholder="如：金小花测试库DDL同步" maxlength="100"></el-input>
      </el-form-item>
      <el-form-item label="所属项目">
        <el-select v-model="form.project" placeholder="选择项目后加载数据源" style="width:100%;" @change="loadInstances">
          <el-option v-for="p in projects" :key="p" :label="p" :value="p"></el-option>
        </el-select>
      </el-form-item>
      <el-form-item label="同步范围">
        <span style="color:#999;">全部库（mysql / information_schema / performance_schema / sys 自动跳过）</span>
      </el-form-item>
      <el-form-item label="数据源">
        <div v-loading="instancesLoading" style="width:100%;">
          <div v-if="!form.project" style="color:#999;">请先选择项目</div>
          <div v-else-if="!instances.length" style="color:#999;">该项目暂无数据源</div>
          <div v-for="inst in instances" :key="inst.id"
               style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;">
            <el-checkbox v-model="inst.checked">
              <b>[[ inst.name ]]</b>
              <span style="color:#999;margin-left:6px;">[[ inst.host ]][[ inst.port ? ':' + inst.port : '' ]]</span>
            </el-checkbox>
            <el-checkbox v-model="inst.ignore" :disabled="!inst.checked">忽略同步（只发不收）</el-checkbox>
          </div>
          <div v-if="instances.length" style="color:#999;font-size:12px;margin-top:6px;">
            勾选参与同步（至少2个）；「忽略同步」的源不执行其他源的变更，但自身变更仍会分发给其他源
          </div>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="formVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="saveTask">保存</el-button>
    </template>
  </el-dialog>

  <!-- 同步日志弹窗（SSE 实时日志流） -->
  <el-dialog v-model="logsVisible" :title="'同步日志' + (currentTaskName ? ' - ' + currentTaskName : '')"
             width="1080px" top="4vh" destroy-on-close @close="closeLogStream">
    <div class="toolbar" style="margin-bottom:12px;">
      <el-tag size="small" :type="streamConnected ? 'success' : 'danger'">
        [[ streamConnected ? '实时监听中' : '连接已断开' ]]
      </el-tag>
      <span style="color:#999;font-size:12px;margin-left:8px;">新变更自动追加，无需手动刷新</span>
    </div>
    <div ref="logBox" class="ddl-log-terminal">
      <div v-if="!logs.length" style="color:#666;">暂无同步日志；在任一勾选数据源执行 DDL 后，变更将实时出现在这里。</div>
      <div v-for="(log, idx) in logs" :key="idx" class="ddl-log-item">
        <div class="ddl-log-head">
          <span class="lg-time">[[ log.created_at ]]</span>
          <span class="lg-src">[[ log.source_name ]]</span>
          <span class="lg-db" v-if="log.schema_name">数据库：[[ log.schema_name ]]</span>
          <span class="lg-type" :class="'lg-' + (log.status || 'ok')">[[ log.ddl_type ]]</span>
        </div>
        <div class="ddl-log-sql">
          <button class="sql-copy-btn" title="复制 SQL" @click="copySql(log.sql_text)">复制</button>
          <pre><code class="hljs language-sql" v-html="highlightSql(log.sql_text)"></code></pre>
        </div>
        <template v-if="log.targets && log.targets.length">
          <div v-for="t in log.targets" :key="t.id" class="ddl-log-tgt"
               :class="'lg-' + t.status">
            <span>→ [[ t.name ]]：[[ t.status === 'ok' ? '✓ 成功' : (t.status === 'failed' ? '✗ 失败' : '忽略') ]]</span>
            <span v-if="t.error" class="lg-err">[[ t.error ]]</span>
          </div>
        </template>
        <div v-else-if="log.error" class="ddl-log-tgt lg-skipped">[[ log.error ]]</div>
      </div>
    </div>
  </el-dialog>
</div>
  `,

  data() {
    return {
      loading: false,
      tasks: [],
      instanceNameMap: {},
      projects: [],
      instances: [],
      instancesLoading: false,
      formVisible: false,
      saving: false,
      form: { id: null, name: '', project: '' },
      logsVisible: false,
      logs: [],
      currentTaskId: null,
      currentTaskName: '',
      logStream: null,
      streamConnected: false,
    };
  },

  computed: {
    canEdit() {
      return !!(this.$auth && this.$auth.hasPermission('op:ddl_sync'));
    },
    // 数据源id → 可读名称 + 监听状态 + 忽略标记
    taskRows() {
      return this.tasks.map(t => ({
        ...t,
        source_names: (t.sources || []).map(id => ({
          id,
          name: this.instanceNameMap[id] || id,
          ignored: (t.ignored || []).includes(id),
          listening: !!(t.listening && t.listening[id]),
        })),
      }));
    },
  },

  mounted() {
    this.loadTasks();
    this.loadInstanceNames();
  },

  methods: {
    // ── 任务列表 ──
    loadTasks() {
      this.loading = true;
      ajax('GET', '/api/database/ddl-sync/tasks', null, (res) => {
        this.loading = false;
        if (res.code === 200) {
          this.tasks = res.data || [];
        } else {
          ElementPlus.ElMessage.error(res.msg || '加载任务失败');
        }
      });
    },

    // 全量数据源名称映射（列表展示用）
    loadInstanceNames() {
      ajax('GET', '/api/database/ddl-sync/instances', null, (res) => {
        if (res.code === 200) {
          const map = {};
          (res.data || []).forEach(i => { map[i.id] = i.name; });
          this.instanceNameMap = map;
        }
      });
    },

    // ── 弹窗：新建 ──
    openCreate() {
      this.form = { id: null, name: '', project: '' };
      this.instances = [];
      this.loadProjects();
      this.formVisible = true;
    },

    // ── 弹窗：编辑（回显勾选状态） ──
    openEdit(task) {
      this.form = { id: task.id, name: task.name, project: task.project };
      this.instances = [];
      this.loadProjects();
      this.formVisible = true;
      this.loadInstances(task.project, task.sources || [], task.ignored || []);
    },

    loadProjects() {
      ajax('GET', '/api/database/ddl-sync/projects', null, (res) => {
        if (res.code === 200) this.projects = res.data || [];
      });
    },

    loadInstances(project, selectedIds, ignoredIds) {
      this.instances = [];
      if (!project) return;
      this.instancesLoading = true;
      const srcSet = new Set(selectedIds || []);
      const ignSet = new Set(ignoredIds || []);
      ajax('GET', `/api/database/ddl-sync/instances?project=${encodeURIComponent(project)}`, null, (res) => {
        this.instancesLoading = false;
        if (res.code === 200) {
          this.instances = (res.data || []).map(i => ({
            ...i,
            checked: srcSet.has(i.id),
            ignore: ignSet.has(i.id),
          }));
        } else {
          ElementPlus.ElMessage.error(res.msg || '加载数据源失败');
        }
      });
    },

    // ── 保存（新建/更新） ──
    saveTask() {
      if (!this.form.name.trim()) { ElementPlus.ElMessage.warning('请输入任务名称'); return; }
      if (!this.form.project) { ElementPlus.ElMessage.warning('请选择项目'); return; }
      const checked = this.instances.filter(i => i.checked);
      if (checked.length < 2) { ElementPlus.ElMessage.warning('至少勾选2个数据源'); return; }
      const payload = {
        name: this.form.name.trim(),
        project: this.form.project,
        sources: checked.map(i => i.id),
        ignored: checked.filter(i => i.ignore).map(i => i.id),
      };
      this.saving = true;
      const isEdit = !!this.form.id;
      const url = isEdit ? `/api/database/ddl-sync/tasks/${this.form.id}` : '/api/database/ddl-sync/tasks';
      ajax(isEdit ? 'PUT' : 'POST', url, payload, (res) => {
        this.saving = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success('保存成功，监听配置已即时生效');
          this.formVisible = false;
          this.loadTasks();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      });
    },

    // ── 启停 ──
    toggleTask(task) {
      ajax('POST', `/api/database/ddl-sync/tasks/${task.id}/toggle`, {}, (res) => {
        if (res.code === 200) {
          ElementPlus.ElMessage.success(task.enabled ? '已停用' : '已启用');
          this.loadTasks();
        } else {
          ElementPlus.ElMessage.error(res.msg || '操作失败');
        }
      });
    },

    // ── 删除 ──
    deleteTask(task) {
      ajax('DELETE', `/api/database/ddl-sync/tasks/${task.id}`, null, (res) => {
        if (res.code === 200) {
          ElementPlus.ElMessage.success('删除成功');
          this.loadTasks();
        } else {
          ElementPlus.ElMessage.error(res.msg || '删除失败');
        }
      });
    },

    // ── 日志（SSE 实时流） ──
    openLogs(task) {
      this.currentTaskId = task.id;
      this.currentTaskName = task.name || '';
      this.logs = [];
      this.logsVisible = true;
      this.connectLogStream();
    },

    connectLogStream() {
      this.closeLogStream();
      const token = localStorage.getItem('auth_token') || '';
      const url = `/api/database/ddl-sync/logs/stream/${this.currentTaskId}?token=${encodeURIComponent(token)}`;
      const es = new EventSource(url);
      this.logStream = es;
      es.onopen = () => { this.streamConnected = true; };
      es.onmessage = (e) => {
        try {
          this.logs.push(JSON.parse(e.data));
          // 历史回放/长流防内存膨胀：仅保留最近 500 条
          if (this.logs.length > 500) this.logs.splice(0, this.logs.length - 500);
          nextTick(() => {
            const box = this.$refs.logBox;
            if (box) box.scrollTop = box.scrollHeight;
          });
        } catch (err) { /* 忽略非法帧 */ }
      };
      es.onerror = () => {
        // 断连（服务重启/网络抖动/心跳超时）：EventSource 按浏览器策略自动重连（约 3s），
        // 不主动 close——断开后自动恢复，避免"总是显示断开"
        this.streamConnected = false;
      };
    },

    closeLogStream() {
      if (this.logStream) {
        this.logStream.close();
        this.logStream = null;
      }
      this.streamConnected = false;
    },

    // SQL 语法高亮（highlight.js；无库时回退纯文本）
    highlightSql(sql) {
      if (window.hljs && sql) {
        try {
          return window.hljs.highlight(String(sql), { language: 'sql' }).value;
        } catch (e) { /* fallthrough */ }
      }
      return String(sql || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },

    // 复制 SQL 到剪贴板
    copySql(sql) {
      const text = String(sql || '');
      const done = () => { this.$message?.({ message: 'SQL 已复制', type: 'success', duration: 1500 }); };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(done).catch(() => this._copyFallback(text, done));
      } else {
        this._copyFallback(text, done);
      }
    },

    _copyFallback(text, done) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        done();
      } catch (e) {
        this.$message?.({ message: '复制失败，请手动选择复制', type: 'warning', duration: 2000 });
      }
    },
  },

  beforeUnmount() {
    this.closeLogStream();
  },
};

// ── 终端式日志流样式 ──
(function() {
  if (document.getElementById('ddl-sync-log-style')) return;
  const style = document.createElement('style');
  style.id = 'ddl-sync-log-style';
  style.textContent = `
.ddl-log-terminal {
  background: #1e1e1e; color: #d4d4d4; border-radius: 6px;
  padding: 12px 14px; height: 62vh; overflow-y: auto;
  font-family: Consolas, 'Courier New', monospace; font-size: 13px;
}
.ddl-log-item { padding: 6px 0; border-bottom: 1px dashed #3a3a3a; }
.ddl-log-item:last-child { border-bottom: none; }
.ddl-log-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.lg-time { color: #888; }
.lg-src { color: #4fc3f7; font-weight: bold; }
.lg-db { color: #ce9178; }
.lg-type { font-weight: bold; padding: 0 6px; border-radius: 3px; background: #333; }
.lg-type.lg-ok { color: #67c23a; }
.lg-type.lg-failed { color: #f56c6c; }
.lg-type.lg-skipped { color: #e6a23c; }
.ddl-log-sql {
  position: relative; margin: 6px 0 4px; border-radius: 4px; overflow: hidden;
}
.ddl-log-sql pre {
  margin: 0; padding: 10px 12px; background: #252526; border-radius: 4px;
  white-space: pre-wrap; word-break: break-all; max-height: 220px; overflow: auto;
}
.ddl-log-sql code { font-family: Consolas, Menlo, monospace; font-size: 12px; }
.ddl-log-sql .sql-copy-btn {
  position: absolute; top: 6px; right: 8px; z-index: 2;
  padding: 2px 10px; font-size: 12px; line-height: 1.6;
  color: #d0d0d0; background: rgba(255,255,255,0.08); border: 1px solid #4a4a4a;
  border-radius: 4px; cursor: pointer; opacity: 0.7;
}
.ddl-log-sql:hover .sql-copy-btn { opacity: 1; }
.ddl-log-sql .sql-copy-btn:hover { background: rgba(255,255,255,0.18); }
.ddl-log-tgt { line-height: 1.8; }
.ddl-log-tgt.lg-ok { color: #67c23a; }
.ddl-log-tgt.lg-failed { color: #f56c6c; }
.ddl-log-tgt.lg-skipped { color: #e6a23c; }
.lg-err { color: #f89898; margin-left: 10px; word-break: break-all; }
`;
  document.head.appendChild(style);
})();
