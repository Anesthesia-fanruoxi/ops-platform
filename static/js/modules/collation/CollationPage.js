const CollationPage = {
  name: 'CollationPage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
<div class="collation-page">
  <div class="cp-layout">
    <!-- ══ 左侧：实例卡片 + 日志 ══ -->
    <div class="cp-sidebar">
      <div class="cp-card">
        <div class="cp-sidebar-section">
          <div class="cp-sidebar-title">MySQL 实例</div>
          <div style="margin-bottom:10px">
            <el-radio-group v-model="selectedProject" size="small">
              <el-radio label="">全部</el-radio>
              <el-radio v-for="p in projects" :key="p" :label="p">[[ p ]]</el-radio>
            </el-radio-group>
          </div>
          <el-input v-model="searchText" placeholder="搜索数据源..." clearable size="small"
                    prefix-icon="Search" style="margin-bottom:10px" />
          <div class="cp-ds-list">
            <div v-if="loadingInstances" class="cp-loading">加载中...</div>
            <div v-else-if="!filteredInstances.length" class="cp-empty">未发现 MySQL 实例</div>
            <div v-for="inst in filteredInstances" :key="inst.id"
                 class="cp-ds-card" :class="{active: activeInstance && activeInstance.id === inst.id, connecting: connectingId === inst.id}"
                 @click="selectInstance(inst)">
              <div class="cp-ds-card-header">
                <span class="cp-ds-dot" :class="{on: activeInstance && activeInstance.id === inst.id}"></span>
                <span class="cp-ds-name">[[ inst.name ]]</span>
                <span v-if="inst.source_type==='custom'" class="cp-tag cp-tag-purple" style="font-size:10px;padding:1px 6px;margin-left:4px">自定义</span>
                <span class="cp-ds-host">[[ inst.host ]]:[[ inst.port ]]</span>
                <span class="cp-ds-arrow">▶</span>
              </div>
              <div class="cp-ds-body" v-if="activeInstance && activeInstance.id === inst.id">
                <div v-if="loadingDbs" class="cp-loading" style="padding:12px">连接中...</div>
                <div v-else-if="!databases.length" class="cp-empty" style="padding:12px">无数据库</div>
                <div v-for="db in databases" :key="db.SCHEMA_NAME"
                     class="cp-db-row" :class="{active: activeDb === db.SCHEMA_NAME}"
                     @click.stop="selectDb(db.SCHEMA_NAME)">
                  <span class="db-name">[[ db.SCHEMA_NAME ]]</span>
                  <span class="db-cell">[[ db.DEFAULT_CHARACTER_SET_NAME ]]</span>
                  <span class="db-cell">[[ db.DEFAULT_COLLATION_NAME ]]</span>
                  <button v-if="!dbOk(db)" class="cp-btn cp-btn-warning" style="font-size:10px;padding:2px 8px" @click.stop="fixSingleDatabase(db.SCHEMA_NAME)">修复</button>
                  <span v-else class="cp-tag cp-tag-success" style="font-size:10px;padding:1px 6px">符合</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ══ 右侧：内容区 ══ -->
    <div class="cp-content">
      <!-- 未选择数据库时的欢迎页 -->
      <div v-if="!activeDb" class="cp-welcome">
        <div class="cp-welcome-icon">🗄️</div>
        <div class="cp-welcome-text">MySQL 排序规则校验</div>
        <div class="cp-welcome-sub">选择左侧实例和数据库开始校验</div>
      </div>

      <template v-else>
        <!-- 统计卡片 -->
        <div class="cp-stats">
          <div class="cp-stat-card">
            <div class="icon" style="background:#eff6ff;color:#2563eb">📊</div>
            <div class="value" style="color:#2563eb">[[ stats.total ]]</div>
            <div class="label">总表数</div>
          </div>
          <div class="cp-stat-card">
            <div class="icon" style="background:#ecfdf5;color:#059669">✓</div>
            <div class="value" style="color:#059669">[[ stats.ok ]]</div>
            <div class="label">已符合</div>
          </div>
          <div class="cp-stat-card">
            <div class="icon" style="background:#fef2f2;color:#dc2626">!</div>
            <div class="value" style="color:#dc2626">[[ stats.needFix ]]</div>
            <div class="label">需修复表</div>
          </div>
          <div class="cp-stat-card">
            <div class="icon" style="background:#fffbeb;color:#d97706">⚠</div>
            <div class="value" style="color:#d97706">[[ stats.colIssues ]]</div>
            <div class="label">字段问题表</div>
          </div>
        </div>

        <!-- 操作栏 -->
        <div class="cp-card" style="flex-shrink:0">
          <div class="cp-card-body" style="padding:12px 20px">
            <div class="cp-form-row">
              <div class="cp-form-group">
                <span class="cp-form-label">行数阈值</span>
                <input class="cp-form-input" type="number" v-model.number="threshold" style="width:120px" />
              </div>
              <button class="cp-btn cp-btn-warning cp-btn-sm" @click="confirmFixAllTables" :disabled="!stats.needFix">一键修复所有表</button>
              <button class="cp-btn cp-btn-primary cp-btn-sm" @click="fixDatabase" :disabled="dbLevelOk">修复库排序</button>
              <a class="cp-btn cp-btn-outline cp-btn-sm" :href="reportUrl" target="_blank" style="text-decoration:none">导出报告</a>
              <button v-if="fixLogs.length && !fixLogVisible" class="cp-btn cp-btn-outline cp-btn-sm" @click="reopenFixLog">查看日志</button>
            </div>
          </div>
        </div>

        <!-- 表/字段 双 tab -->
        <div class="cp-card cp-tab-panel">
          <div class="cp-card-header">
            <div class="cp-panel-tabs">
              <div class="cp-panel-tab" :class="{active: activeTab==='tables'}" @click="activeTab='tables'">
                表列表 <span v-if="stats.needFix" class="cp-tag cp-tag-danger" style="font-size:11px">[[ stats.needFix ]]</span>
              </div>
              <div class="cp-panel-tab" :class="{active: activeTab==='columns'}" @click="switchToColumns">
                字段问题 <span v-if="stats.colIssues" class="cp-tag cp-tag-warning" style="font-size:11px">[[ stats.colIssues ]]</span>
              </div>
            </div>
          </div>
          <div class="cp-tab-body">
            <!-- 表列表 -->
            <div v-show="activeTab==='tables'" class="cp-tab-pane">
              <div class="cp-filter-bar">
                <el-input v-model="tableFilter" placeholder="搜索过滤表名..." clearable size="small" prefix-icon="Search" style="width:240px" />
                <span class="cp-filter-count">[[ filteredTables.length ]] / [[ tables.length ]] 张表</span>
              </div>
              <div class="cp-tab-scroll">
                <div v-if="loadingTables" class="cp-loading">加载中...</div>
                <table v-else-if="filteredTables.length" class="tbl-fixed tbl-tables">
                  <thead><tr><th>表名</th><th>注释</th><th>字符集</th><th>排序规则</th><th>行数</th><th>字段问题</th><th>操作</th></tr></thead>
                  <tbody>
                    <tr v-for="t in filteredTables" :key="t.TABLE_NAME">
                      <td :title="t.TABLE_NAME"><strong>[[ t.TABLE_NAME ]]</strong></td>
                      <td><span style="color:#64748b;font-size:12px">[[ t.TABLE_COMMENT || '-' ]]</span></td>
                      <td>[[ t.TABLE_CHARSET ]]</td>
                      <td>[[ t.TABLE_COLLATION ]]</td>
                      <td><span style="color:#94a3b8">≈[[ (t.TABLE_ROWS || 0).toLocaleString() ]]</span></td>
                      <td>
                        <span v-if="t.COLUMN_ISSUE_COUNT" class="cp-tag cp-tag-warning">[[ t.COLUMN_ISSUE_COUNT ]] 个</span>
                        <span v-else class="cp-tag cp-tag-success">无</span>
                      </td>
                      <td>
                        <div style="display:flex;gap:6px;align-items:center;white-space:nowrap">
                          <button class="cp-btn cp-btn-outline cp-btn-sm" @click="switchToColumns">查看列</button>
                          <button v-if="t.table_need_fix" class="cp-btn cp-btn-warning cp-btn-sm" @click="confirmFixTable(t)">修复表</button>
                          <span v-else class="cp-tag cp-tag-success">符合表</span>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="cp-empty">[[ tables.length ? '无匹配的表' : '无数据' ]]</div>
              </div>
            </div>
            <!-- 字段问题 -->
            <div v-show="activeTab==='columns'" class="cp-tab-pane">
              <div class="cp-filter-bar">
                <el-input v-model="columnFilter" placeholder="搜索过滤表名..." clearable size="small" prefix-icon="Search" style="width:240px" />
                <span class="cp-filter-count">[[ filteredColumnIssues.length ]] / [[ columnIssues.length ]] 张表</span>
              </div>
              <div class="cp-tab-scroll">
                <div v-if="loadingColIssues" class="cp-loading">加载中...</div>
                <div v-else-if="!columnIssues.length" class="cp-empty">🎉 所有字段均符合排序规则</div>
                <div v-else-if="!filteredColumnIssues.length" class="cp-empty">无匹配的表</div>
                <div v-else style="padding:12px">
                  <div v-for="group in filteredColumnIssues" :key="group.table" class="cp-colf-group">
                    <div class="cp-colf-group-header">
                      <span>[[ group.table ]]</span>
                      <span class="cnt">[[ group.columns.length ]] 个字段</span>
                      <span class="cp-est-rows">≈ [[ (group.row_count || 0).toLocaleString() ]] 行</span>
                      <button class="cp-btn cp-btn-purple cp-btn-sm" style="margin-left:auto" @click="fixTableColumns({TABLE_NAME: group.table, COLUMN_ISSUE_COUNT: group.columns.length})">修复该表全部字段</button>
                    </div>
                    <div class="cp-colf-cols">
                      <table class="cp-issue-table">
                        <thead><tr><th>字段</th><th>类型</th><th>字符集</th><th>排序规则</th></tr></thead>
                        <tbody>
                          <tr v-for="col in group.columns" :key="col.name">
                            <td><code class="cp-code">[[ col.name ]]</code></td>
                            <td>[[ col.type ]]</td>
                            <td><span class="cp-tag cp-tag-warning" style="font-size:11px">[[ col.charset ]]</span></td>
                            <td><code class="cp-code">[[ col.collation ]]</code></td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>

  <!-- ══ 确认弹窗 ══ -->
  <div v-if="confirmModal.show" class="cp-modal-mask" @click.self="confirmModal.show=false">
    <div class="cp-modal-box">
      <div class="cp-modal-header">
        <span>[[ confirmModal.title ]]</span>
        <button class="cp-modal-close" @click="confirmModal.show=false">✕</button>
      </div>
      <div class="cp-modal-body">
        <div v-if="confirmModal.messageHtml" v-html="confirmModal.messageHtml"></div>
        <div v-else>[[ confirmModal.message ]]</div>
        <div v-if="confirmModal.warning" class="cp-modal-warning">⚠️ [[ confirmModal.warning ]]</div>
      </div>
      <div class="cp-modal-footer">
        <button class="cp-btn cp-btn-outline" @click="confirmModal.show=false">取消</button>
        <button class="cp-btn cp-btn-primary" @click="confirmModal.onConfirm" :disabled="confirmModal.loading">
          [[ confirmModal.loading ? '执行中...' : '确认执行' ]]
        </button>
      </div>
    </div>
  </div>

  <!-- ══ 一键修复表预览弹窗 ══ -->
  <div v-if="fixAllModal.show" class="cp-modal-mask" @click.self="fixAllModal.show=false">
    <div class="cp-modal-box" style="width:640px">
      <div class="cp-modal-header">
        <span>🔧 一键修复表 · 预览确认</span>
        <button class="cp-modal-close" @click="fixAllModal.show=false">✕</button>
      </div>
      <div class="cp-modal-body" style="max-height:50vh">
        <div class="cp-modal-warning" style="margin-top:0;margin-bottom:12px">⚠️ 修复表将重建整表并连带转换全部字段，超过阈值的表将自动跳过（按修复时实际行数判定），请务必在业务低谷期执行。</div>
        <div v-for="group in fixAllModal.groups" :key="group.table" class="cp-colf-group">
          <div class="cp-colf-group-header">
            <span>[[ group.table ]]</span>
            <span class="cnt">[[ group.columns.length ]] 个字段</span>
          </div>
          <div class="cp-colf-cols">
            <div v-if="!group.columns.length" class="cp-colf-item" style="color:#94a3b8">该表无字段级问题，仅表级排序规则不符</div>
            <div v-for="col in group.columns" :key="col.name" class="cp-colf-item">
              <span class="col-name">[[ col.name ]]</span>
              <span class="col-type">[[ col.type ]]</span>
              <span class="col-coll">[[ col.collation ]]</span>
            </div>
          </div>
        </div>
        <div v-if="!fixAllModal.groups.length" class="cp-empty">🎉 没有需要修复的表</div>
      </div>
      <div class="cp-modal-footer" style="justify-content:space-between">
        <span style="font-size:13px;color:#64748b">共 <b style="color:#f59e0b">[[ fixAllModal.groups.length ]]</b> 张表</span>
        <div style="display:flex;gap:10px">
          <button class="cp-btn cp-btn-outline" @click="fixAllModal.show=false">取消</button>
          <button class="cp-btn cp-btn-warning" @click="doFixAllTables" :disabled="!fixAllModal.groups.length || fixAllModal.loading">
            [[ fixAllModal.loading ? '修复中...' : '确认修复' ]]
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ 字段修复预览弹窗 ══ -->
  <div v-if="colFixModal.show" class="cp-modal-mask" @click.self="colFixModal.show=false">
    <div class="cp-modal-box" style="width:640px">
      <div class="cp-modal-header">
        <span>🔧 修复字段 · [[ colFixModal.singleTable ]]</span>
        <button class="cp-modal-close" @click="colFixModal.show=false">✕</button>
      </div>
      <div class="cp-modal-body" style="max-height:50vh">
        <div class="cp-modal-warning" style="margin-top:0;margin-bottom:12px">⚠️ 单表指定修复将无视数据量阈值限制，可能造成长时间锁表，请务必在业务低谷期执行。取消勾选即可排除不想修复的字段。</div>
        <div v-for="group in colFixModal.groups" :key="group.table" class="cp-colf-group">
          <div class="cp-colf-group-header">
            <input type="checkbox" :checked="isGroupAllChecked(group)" @click.stop="toggleGroupCheck(group)" style="width:15px;height:15px;accent-color:#6366f1" />
            <span>[[ group.table ]]</span>
            <span class="cnt">[[ getCheckedCount(group) ]]/[[ group.columns.length ]]</span>
            <span class="cp-est-rows">≈ [[ (group.row_count || 0).toLocaleString() ]] 行</span>
          </div>
          <div class="cp-colf-cols">
            <div v-for="col in group.columns" :key="col.name" class="cp-colf-item" :class="{unchecked: !col._checked}">
              <input type="checkbox" v-model="col._checked" />
              <span class="col-name">[[ col.name ]]</span>
              <span class="col-type">[[ col.type ]]</span>
              <span class="col-coll">[[ col.collation ]]</span>
            </div>
          </div>
        </div>
        <div v-if="!colFixModal.groups.length" class="cp-empty">🎉 没有需要修复的字段</div>
      </div>
      <div class="cp-modal-footer" style="justify-content:space-between">
        <span style="font-size:13px;color:#64748b">已选 <b style="color:#6366f1">[[ colFixTotalChecked ]]</b> 个字段</span>
        <div style="display:flex;gap:10px">
          <button class="cp-btn cp-btn-outline" @click="colFixModal.show=false">取消</button>
          <button class="cp-btn cp-btn-danger" @click="executeColFix" :disabled="!colFixTotalChecked || colFixModal.loading">
            [[ colFixModal.loading ? '修复中...' : '确认修复' ]]
          </button>
        </div>
      </div>
    </div>
  </div>
  <!-- ══ 修复日志弹框（SSE 实时推送） ══ -->
  <div v-if="fixLogVisible" class="cp-modal-mask">
    <div class="cp-modal-box" style="width:65vw">
      <div class="cp-modal-header">
        <span>🔧 [[ fixLogTitle ]]</span>
        <button class="cp-modal-close" @click="fixLogVisible=false">✕</button>
      </div>
      <div class="cp-plog" ref="fixLogContainer">
        <div v-for="(log, i) in fixLogs" :key="i" class="cp-plog-line">
          <span class="cp-plog-time">[[ log.time || '' ]]</span>
          <span v-if="log.op" class="cp-plog-op">[[ log.op ]]</span>
          <span v-if="log.source" class="cp-plog-src">[[ log.source ]]</span>
          <span v-if="log.database && log.database !== '-'" class="cp-plog-db">[[ log.database ]]</span>
          <span :class="'cp-plog-msg cp-plog-lvl-' + (log.level || 'info').toLowerCase()">[[ log.message || '' ]]</span>
        </div>
        <div v-if="fixLogDone" class="cp-plog-line">
          <span :class="'cp-plog-msg cp-plog-lvl-' + (fixLogSuccess ? 'done' : 'failed')">[[ fixLogSuccess ? '=== 修复完成 ===' : '=== 修复失败 ===' ]]</span>
        </div>
      </div>
      <div class="cp-modal-footer" style="justify-content:flex-end">
        <button class="cp-btn cp-btn-outline" @click="fixLogVisible=false">关闭</button>
      </div>
    </div>
  </div>
</div>
`,

  data() {
    return {
      // 实例
      instances: [],
      loadingInstances: false,
      activeInstance: null,
      connectingId: null,
      // 过滤
      selectedProject: '',
      searchText: '',
      // 数据库
      databases: [],
      loadingDbs: false,
      activeDb: '',
      // 表
      tables: [],
      loadingTables: false,
      activeTab: 'tables',
      tableFilter: '',
      // 字段问题
      columnIssues: [],
      loadingColIssues: false,
      columnFilter: '',
      // 阈值
      threshold: 100000,
      // 确认弹窗
      confirmModal: { show: false, title: '', message: '', messageHtml: '', warning: '', tables: [], summary: '', loading: false, onConfirm: null },
      // 一键修复表弹窗（树形预览，字段常驻展示）
      fixAllModal: { show: false, groups: [], loading: false },
      // 字段修复弹窗
      colFixModal: { show: false, singleTable: '', groups: [], loading: false },
      // 修复日志弹框（SSE）
      fixLogVisible: false,
      fixLogTitle: '',
      fixLogs: [],
      fixLogDone: false,
      fixLogSuccess: false,
      fixEventSource: null,
    };
  },

  computed: {
    // 项目列表（去重，排除无项目标识的实例）
    projects() {
      const set = new Set();
      for (const inst of this.instances) {
        if (inst.project) set.add(inst.project);
      }
      return Array.from(set).sort();
    },
    // 过滤后的实例：项目单选 + 搜索（自动发现无项目不展示，自定义始终展示）
    filteredInstances() {
      const kw = this.searchText.trim().toLowerCase();
      return this.instances.filter(inst => {
        // 自动发现无项目标识不展示，自定义数据源始终展示
        if (inst.source_type !== 'custom' && !inst.project) return false;
        if (this.selectedProject && inst.project !== this.selectedProject) return false;
        if (kw && !inst.name.toLowerCase().includes(kw)) return false;
        return true;
      });
    },
    stats() {
      const total = this.tables.length;
      const needFix = this.tables.filter(t => t.need_fix).length;
      const colIssues = this.tables.filter(t => t.COLUMN_ISSUE_COUNT > 0).length;
      return { total, ok: total - needFix, needFix, colIssues };
    },
    // 表名搜索过滤 + 排序（不符合优先，再按字母序）
    filteredTables() {
      const kw = this.tableFilter.trim().toLowerCase();
      let list = kw ? this.tables.filter(t => t.TABLE_NAME.toLowerCase().includes(kw)) : this.tables;
      return list.slice().sort((a, b) => {
        if (a.need_fix !== b.need_fix) return a.need_fix ? -1 : 1;
        return a.TABLE_NAME.localeCompare(b.TABLE_NAME);
      });
    },
    // 字段问题表名搜索过滤
    filteredColumnIssues() {
      const kw = this.columnFilter.trim().toLowerCase();
      if (!kw) return this.columnIssues;
      return this.columnIssues.filter(g => g.table.toLowerCase().includes(kw));
    },
    dbLevelOk() {
      const db = this.databases.find(d => d.SCHEMA_NAME === this.activeDb);
      if (!db) return true;
      return db.DEFAULT_CHARACTER_SET_NAME === 'utf8mb4' && db.DEFAULT_COLLATION_NAME === 'utf8mb4_0900_ai_ci';
    },
    reportUrl() {
      if (!this.activeInstance || !this.activeDb) return '#';
      const token = localStorage.getItem('auth_token') || '';
      return `/api/collation/report/${this.activeDb}?instance_id=${this.activeInstance.id}&token=${token}`;
    },
    colFixTotalChecked() {
      let count = 0;
      for (const g of this.colFixModal.groups) {
        count += g.columns.filter(c => c._checked).length;
      }
      return count;
    }
  },

  methods: {
    dbOk(db) {
      return db.DEFAULT_CHARACTER_SET_NAME === 'utf8mb4' && db.DEFAULT_COLLATION_NAME === 'utf8mb4_0900_ai_ci';
    },

    // ── 加载实例 ──
    loadInstances() {
      this.loadingInstances = true;
      ajax('GET', '/api/collation/instances', null, (res) => {
        this.loadingInstances = false;
        if (res.code === 200) {
          const data = res.data || {};
          // 兼容新分组格式 {auto:[], custom:[]} 和旧数组格式
          if (Array.isArray(data)) {
            this.instances = data;
          } else {
            this.instances = [...(data.auto || []), ...(data.custom || [])];
          }
        } else {
          ElementPlus.ElMessage.error(res.msg || '获取实例失败');
        }
      });
    },

    // ── 选择实例 ──
    selectInstance(inst) {
      if (this.connectingId) return;  // 连接中忽略点击
      // 再次点击已展开的实例：收起（相当于断开连接）
      if (this.activeInstance && this.activeInstance.id === inst.id) {
        this.activeInstance = null;
        this.activeDb = '';
        this.databases = [];
        this.tables = [];
        this.columnIssues = [];
        return;
      }
      this.activeInstance = inst;
      this.activeDb = '';
      this.tables = [];
      this.columnIssues = [];
      this.databases = [];
      this.connectingId = inst.id;
      this.loadingDbs = true;
      ajax('GET', `/api/collation/databases?instance_id=${inst.id}`, null, (res) => {
        this.connectingId = null;
        this.loadingDbs = false;
        if (res.code === 200) {
          this.databases = res.data || [];
        } else {
          ElementPlus.ElMessage.error(res.msg || '连接失败');
          this.activeInstance = null;
        }
      });
    },

    // ── 选择数据库 ──
    selectDb(dbName) {
      if (this.activeDb === dbName) return;
      this.activeDb = dbName;
      this.activeTab = 'tables';
      this.tableFilter = '';
      this.columnFilter = '';
      this.loadTables();
    },

    // ── 加载表 ──
    loadTables() {
      this.loadingTables = true;
      const url = `/api/collation/tables/${this.activeDb}?instance_id=${this.activeInstance.id}`;
      ajax('GET', url, null, (res) => {
        this.loadingTables = false;
        if (res.code === 200) {
          this.tables = res.data || [];
          // 同步加载字段问题，保证修复预览弹窗数据就绪
          this.loadColumnIssues();
        } else {
          ElementPlus.ElMessage.error(res.msg || '加载表失败');
        }
      });
    },

    // ── 切换到字段 tab ──
    switchToColumns() {
      this.activeTab = 'columns';
      if (!this.columnIssues.length && this.stats.colIssues > 0) {
        this.loadColumnIssues();
      }
    },

    loadColumnIssues() {
      this.loadingColIssues = true;
      const url = `/api/collation/column_issues/${this.activeDb}?instance_id=${this.activeInstance.id}`;
      return new Promise((resolve) => {
        ajax('GET', url, null, (res) => {
          this.loadingColIssues = false;
          if (res.code === 200) {
            this.columnIssues = res.data || [];
          } else {
            ElementPlus.ElMessage.error(res.msg || '加载字段问题失败');
          }
          resolve(this.columnIssues);
        });
      });
    },

    // ── 修复单表 ──
    confirmFixTable(t) {
      const issues = t.COLUMN_ISSUES || [];
      const colCount = issues.length;
      let colTip;
      if (colCount) {
        const colsHtml = issues.map(c => `<code class="cp-hl-col">${c.name}</code>`).join('');
        colTip = `此操作会同时修复该表下 <b style="color:#dc2626">${colCount}</b> 个不符合排序规则的字段：<div class="cp-hl-cols">${colsHtml}</div>`;
      } else {
        colTip = '此操作会同时修复该表下所有不符合排序规则的字段。';
      }
      this.confirmModal = {
        show: true,
        title: '修复表排序规则',
        messageHtml: `确认将表 <code class="cp-hl">${t.TABLE_NAME}</code> 的排序规则修改为 <code class="cp-hl">utf8mb4_0900_ai_ci</code>？<br>该表预估数据量 <b style="color:#6366f1">${(t.TABLE_ROWS || 0).toLocaleString()}</b> 行。<br>${colTip}`,
        warning: '单表修复将无视数据量阈值限制，可能造成长时间锁表，请务必在业务低谷期执行。',
        tables: [],
        summary: '',
        loading: false,
        onConfirm: () => { this.doFixTable(t); }
      };
    },

    doFixTable(t) {
      this.confirmModal.loading = true;
      ajax('POST', '/api/collation/fix_table_async', {
        instance_id: this.activeInstance.id,
        database: this.activeDb,
        table: t.TABLE_NAME
      }, (res) => {
        this.confirmModal.loading = false;
        this.confirmModal.show = false;
        if (res.code === 200) {
          this.openFixLog(`修复表 ${t.TABLE_NAME}`, res.data.task_key);
        } else {
          ElementPlus.ElMessage.error(res.msg || '修复失败');
        }
      });
    },

    // ── 批量修复表（树形预览） ──
    confirmFixAllTables() {
      const needFix = this.tables.filter(t => t.need_fix);
      if (!needFix.length) {
        ElementPlus.ElMessage.success('所有表已符合要求');
        return;
      }
      // 每张表一个节点，展示其问题字段；超阈值的表由后端按实际行数自动跳过
      const groups = needFix.map(t => ({
        table: t.TABLE_NAME,
        columns: (t.COLUMN_ISSUES || []).map(c => ({ name: c.name, type: c.type, collation: c.collation }))
      }));
      this.fixAllModal = { show: true, groups, loading: false };
    },

    doFixAllTables() {
      this.fixAllModal.loading = true;
      ajax('POST', '/api/collation/fix_all_tables_async', {
        instance_id: this.activeInstance.id,
        database: this.activeDb,
        threshold: this.threshold
      }, (res) => {
        this.fixAllModal.loading = false;
        this.fixAllModal.show = false;
        if (res.code === 200) {
          this.openFixLog('一键修复所有表', res.data.task_key);
        } else {
          ElementPlus.ElMessage.error(res.msg || '批量修复失败');
        }
      });
    },

    // ── 修复库级排序 ──
    fixDatabase() {
      this.confirmModal = {
        show: true,
        title: '修复数据库排序规则',
        message: `确认将数据库 ${this.activeDb} 的默认排序规则修改为 utf8mb4_0900_ai_ci？`,
        tables: [],
        summary: '',
        loading: false,
        onConfirm: () => { this.doFixDatabase(); }
      };
    },

    doFixDatabase() {
      this.confirmModal.loading = true;
      ajax('POST', '/api/collation/fix_database_async', {
        instance_id: this.activeInstance.id,
        database: this.activeDb
      }, (res) => {
        this.confirmModal.loading = false;
        this.confirmModal.show = false;
        if (res.code === 200) {
          this.openFixLog(`修复库 ${this.activeDb}`, res.data.task_key);
        } else {
          ElementPlus.ElMessage.error(res.msg || '修复失败');
        }
      });
    },

    // ── 侧边栏单库修复 ──
    fixSingleDatabase(dbName) {
      this.confirmModal = {
        show: true,
        title: '修复数据库排序规则',
        message: `确认将数据库 ${dbName} 的默认排序规则修改为 utf8mb4_0900_ai_ci？`,
        tables: [],
        summary: '',
        loading: false,
        onConfirm: () => { this.doFixSingleDatabase(dbName); }
      };
    },

    doFixSingleDatabase(dbName) {
      this.confirmModal.loading = true;
      ajax('POST', '/api/collation/fix_database_async', {
        instance_id: this.activeInstance.id,
        database: dbName
      }, (res) => {
        this.confirmModal.loading = false;
        this.confirmModal.show = false;
        if (res.code === 200) {
          this.openFixLog(`修复库 ${dbName}`, res.data.task_key);
        } else {
          ElementPlus.ElMessage.error(res.msg || '修复失败');
        }
      });
    },

    // ── 刷新数据库列表（不重置已选库）──
    refreshDatabases() {
      if (!this.activeInstance) return;
      ajax('GET', `/api/collation/databases?instance_id=${this.activeInstance.id}`, null, (res) => {
        if (res.code === 200) {
          this.databases = res.data || [];
        }
      });
    },

    // ── 单表字段修复预览 ──
    async fixTableColumns(table) {
      const count = table.COLUMN_ISSUE_COUNT || 0;
      if (!count) {
        ElementPlus.ElMessage.success('该表字段均已符合');
        return;
      }
      let group = this.columnIssues.find(g => g.table === table.TABLE_NAME);
      if (!group) {
        await this.loadColumnIssues();
        group = this.columnIssues.find(g => g.table === table.TABLE_NAME);
      }
      if (!group) {
        ElementPlus.ElMessage.success('该表字段均已符合');
        return;
      }
      this.colFixModal = {
        show: true,
        singleTable: group.table,
        groups: [{ table: group.table, row_count: group.row_count, columns: group.columns.map(c => ({ ...c, _checked: true })) }],
        loading: false
      };
    },

    isGroupAllChecked(group) {
      return group.columns.every(c => c._checked);
    },

    getCheckedCount(group) {
      return group.columns.filter(c => c._checked).length;
    },

    toggleGroupCheck(group) {
      const allChecked = this.isGroupAllChecked(group);
      group.columns.forEach(c => { c._checked = !allChecked; });
    },

    executeColFix() {
      // 构建 {table: [col_names]}
      const selected = {};
      for (const g of this.colFixModal.groups) {
        const cols = g.columns.filter(c => c._checked).map(c => c.name);
        if (cols.length) selected[g.table] = cols;
      }
      if (!Object.keys(selected).length) {
        ElementPlus.ElMessage.warning('请至少选择一个字段');
        return;
      }
      this.colFixModal.loading = true;
      const body = {
        instance_id: this.activeInstance.id,
        database: this.activeDb,
        threshold: this.threshold,
        columns: selected
      };
      // 单表模式携带 table 参数，后端日志将记录为单表修复
      if (this.colFixModal.singleTable) body.table = this.colFixModal.singleTable;
      const logTitle = `修复字段 · ${this.colFixModal.singleTable}`;
      ajax('POST', '/api/collation/fix_columns_async', body, (res) => {
        this.colFixModal.loading = false;
        this.colFixModal.show = false;
        if (res.code === 200) {
          this.openFixLog(logTitle, res.data.task_key);
        } else {
          ElementPlus.ElMessage.error(res.msg || '字段修复失败');
        }
      });
    },

    // ── 修复日志弹框（SSE 实时推送） ──
    openFixLog(title, taskKey) {
      this.fixLogTitle = title;
      this.fixLogs = [];
      this.fixLogDone = false;
      this.fixLogSuccess = false;
      this.fixLogVisible = true;
      this.connectFixSSE(taskKey);
    },

    reopenFixLog() {
      // 重新打开日志弹框（展示已缓存的日志，不重连 SSE）
      this.fixLogVisible = true;
    },

    connectFixSSE(taskKey) {
      const self = this;
      this.closeFixSSE();
      const token = localStorage.getItem('auth_token') || '';
      const es = new EventSource('/api/collation/stream?task_key=' + encodeURIComponent(taskKey) + '&token=' + encodeURIComponent(token));
      this.fixEventSource = es;
      es.onmessage = function(e) {
        const d = JSON.parse(e.data);
        if (d.done) {
          self.fixLogDone = true;
          self.fixLogSuccess = d.success !== false;
          es.close();
          self.fixEventSource = null;
          self.onFixComplete();
          return;
        }
        self.fixLogs.push(d);
        self.$nextTick(() => {
          const c = self.$refs.fixLogContainer;
          if (c) c.scrollTop = c.scrollHeight;
        });
      };
      es.onerror = function() {
        es.close();
        self.fixEventSource = null;
        if (!self.fixLogDone) {
          self.fixLogDone = true;
          self.fixLogSuccess = false;
          self.fixLogs.push({ level: 'ERROR', message: 'SSE连接失败，无法获取修复进度', time: '' });
        }
      };
    },

    closeFixSSE() {
      if (this.fixEventSource) {
        this.fixEventSource.close();
        this.fixEventSource = null;
      }
    },

    onFixComplete() {
      // 修复结束后刷新数据库与表/字段数据
      this.refreshDatabases();
      if (this.activeDb) {
        this.loadTables();
      }
    }
  },

  created() {
    this.loadInstances();
  },

  beforeUnmount() {
    this.closeFixSSE();
  }
};
