// ============================================================
// MySQL 库结构对比与同步页面
// 源库 → 目标库 单向对比（表/视图/事件），支持一源多目标
// 已选实例源/目标互斥显示；差异按「新建 / 修改 / 删除」三类归组展示
// ============================================================
const SchemaComparePage = {
  name: 'SchemaComparePage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
<div class="collation-page schema-page">
  <!-- ══ 顶部：源/目标选择 ══ -->
  <div class="cp-card" style="flex-shrink:0">
    <div class="cp-card-body" style="padding:14px 20px">
      <div class="sc-select-bar">
        <div class="sc-side sc-side-projects">
          <div class="sc-side-title">📁 项目（点选过滤，源/目标仅显示该项目实例）</div>
          <div class="sc-project-chips">
            <div class="sc-project-chip" :class="{active: !projectFilter}" @click="selectProject('')">全部</div>
            <div v-for="p in projectOptions" :key="p" class="sc-project-chip"
                 :class="{active: projectFilter === p}" @click="selectProject(p)">[[ p ]]</div>
          </div>
        </div>
        <div class="sc-side">
          <div class="sc-side-title">📤 源库（以此为准）</div>
          <div class="sc-side-row">
            <el-select v-model="sourceInstanceId" placeholder="选择实例" size="small" filterable
                       style="width:260px" @change="onSourceInstanceChange">
              <el-option v-for="i in sourceInstanceOptions" :key="i.id" :label="i.label" :value="i.id" />
            </el-select>
            <el-select v-model="sourceDb" placeholder="选择数据库" size="small" filterable
                       style="width:180px" :loading="loadingSourceDbs">
              <el-option v-for="db in sourceDbs" :key="db" :label="db" :value="db" />
            </el-select>
          </div>
        </div>
        <button class="cp-btn cp-btn-outline cp-btn-sm sc-swap" @click="swapSides"
                title="交换源/目标（仅单目标时可用）">⇄</button>
        <div class="sc-side">
          <div class="sc-side-title">📥 目标库（被同步，支持多选，库名同源）</div>
          <div class="sc-side-row">
            <el-select v-model="targetInstanceIds" placeholder="选择目标实例（可多选）" size="small" filterable multiple
                       collapse-tags collapse-tags-tooltip style="width:340px" @change="onTargetInstancesChange">
              <el-option v-for="i in targetInstanceOptions" :key="i.id" :label="i.label" :value="i.id" />
            </el-select>
          </div>
        </div>
        <div class="sc-actions">
          <button class="cp-btn cp-btn-primary" @click="doCompare"
                  :disabled="!canCompare || comparing">
            [[ comparing ? '对比中...' : '开始对比' ]]
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ 结果区 ══ -->
  <div v-if="!compared" class="cp-welcome" style="flex:1">
    <div class="cp-welcome-icon">🔍</div>
    <div class="cp-welcome-text">MySQL 表结构对比</div>
    <div class="cp-welcome-sub">选择源库与一个或多个目标库后点击「开始对比」，可将源库结构同步到目标库</div>
  </div>

  <template v-else>
    <!-- 结果表（多目标用标签页分开显示） -->
    <div class="cp-card cp-tab-panel">
      <div class="cp-card-header">
        <div class="cp-panel-tabs">
          <div v-for="tab in typeTabs" :key="tab.key" class="cp-panel-tab"
               :class="{active: typeFilter === tab.key}" @click="typeFilter = tab.key">
            [[ tab.label ]] <span v-if="tab.count" class="cp-tag cp-tag-info" style="font-size:11px">[[ tab.count ]]</span>
          </div>
        </div>
        <div style="display:flex;gap:10px;align-items:center">
          <el-input v-model="tableFilter" placeholder="搜索对象名..." clearable size="small" prefix-icon="Search" style="width:200px" />
          <button class="cp-btn cp-btn-outline cp-btn-sm" @click="viewSyncSql" :disabled="!needSyncCount">查看同步SQL</button>
          <template v-if="syncAllowed">
            <button class="cp-btn cp-btn-outline cp-btn-sm" @click="selectAllSync" :disabled="!needSyncCount">全选</button>
            <button class="cp-btn cp-btn-outline cp-btn-sm" @click="clearSelection" :disabled="!selectedCount">清除</button>
            <button class="cp-btn cp-btn-warning cp-btn-sm" @click="syncSelected" :disabled="!selectedCount">
              同步所选（[[ selectedCount ]]）
            </button>
            <button class="cp-btn cp-btn-danger cp-btn-sm" @click="confirmSyncAll" :disabled="!needSyncCount">
              一键同步全部（[[ needSyncCount ]]）
            </button>
          </template>
        </div>
      </div>

      <!-- 目标标签页（仅多目标时显示） -->
      <div v-if="compareResults.length > 1" class="cp-panel-tabs sc-target-tabs">
        <div v-for="r in compareResults" :key="r.target.instance_id" class="cp-panel-tab"
             :class="{active: activeTargetId === r.target.instance_id}" @click="activeTargetId = r.target.instance_id">
          📥 [[ r.target.name ]]
          <span v-if="r.summary.missing + r.summary.diff" class="cp-tag cp-tag-warning" style="font-size:11px">[[ r.summary.missing + r.summary.diff ]]</span>
          <span v-else class="cp-tag cp-tag-success" style="font-size:11px">✓</span>
        </div>
      </div>

      <div class="cp-tab-body">
        <!-- 每个目标的差异面板常驻 DOM，切换标签只切显隐，避免大列表重建卡顿 -->
        <div class="cp-tab-scroll" v-for="r in compareResults" :key="r.target.instance_id" v-show="activeResult === r">
          <!-- Navicat 风格：按 创建/修改/删除 分组平铺，每项前置对象类型标签 -->
          <div class="sc-result-header">
            📥 目标：<b>[[ r.target.name ]]</b> · [[ r.target.database ]]
            <span class="sc-result-summary">
              ➕ [[ r.summary.missing ]]　✏️ [[ r.summary.diff ]]　✓ [[ r.summary.identical ]]　？ [[ r.summary.extra ]]
            </span>
          </div>
          <div v-if="typeFilter === 'all' || typeFilter === 'create'">
            <div class="sc-group-title sc-title-create">
              <el-checkbox v-if="syncAllowed" :model-value="isGroupAllSelected('create', r)"
                           :indeterminate="isGroupIndeterminate('create', r)"
                           @change="v => toggleGroupSelect('create', v, r)" />
              ➕ 创建（[[ r.summary.missing ]] 个对象）
            </div>
            <div v-if="groupObjects('create', r).length" class="sc-op-list">
              <div v-for="obj in groupObjects('create', r)" :key="obj.key" class="sc-op-item">
                <el-checkbox v-if="syncAllowed" :model-value="isObjSelected(r, obj)" @change="v => toggleObjSelect(r, obj, v)" style="flex-shrink:0" />
                <span class="cp-tag" :class="typeTagClass(obj.object_type)" style="font-size:10px;flex-shrink:0">[[ obj.object_type ]]</span>
                <code class="cp-code" style="flex-shrink:0">[[ obj.table ]]</code>
                <span class="sc-op-desc">[[ obj.desc ]]</span>
              </div>
            </div>
            <div v-else class="sc-expand-note">无待创建对象</div>
          </div>
          <div v-if="typeFilter === 'all' || typeFilter === 'modify'">
            <div class="sc-group-title sc-title-modify">
              <el-checkbox v-if="syncAllowed" :model-value="isGroupAllSelected('modify', r)"
                           :indeterminate="isGroupIndeterminate('modify', r)"
                           @change="v => toggleGroupSelect('modify', v, r)" />
              ✏️ 修改（[[ r.summary.diff ]] 个对象）
            </div>
            <div v-if="groupObjects('modify', r).length" class="sc-op-list">
              <div v-for="obj in groupObjects('modify', r)" :key="obj.key" class="sc-op-item">
                <el-checkbox v-if="syncAllowed" :model-value="isObjSelected(r, obj)" @change="v => toggleObjSelect(r, obj, v)" style="flex-shrink:0" />
                <span class="cp-tag" :class="typeTagClass(obj.object_type)" style="font-size:10px;flex-shrink:0">[[ obj.object_type ]]</span>
                <code class="cp-code" style="flex-shrink:0">[[ obj.table ]]</code>
                <span class="sc-op-desc">[[ obj.desc ]]</span>
              </div>
            </div>
            <div v-else class="sc-expand-note">无待修改对象</div>
          </div>
          <div v-if="typeFilter === 'all' || typeFilter === 'drop'">
            <div class="sc-group-title sc-title-drop">🗑️ 删除（[[ r.summary.extra ]] 个对象，仅提示不执行）</div>
            <div v-if="groupObjects('drop', r).length" class="sc-op-list">
              <div v-for="obj in groupObjects('drop', r)" :key="obj.key" class="sc-op-item">
                <span class="cp-tag" :class="typeTagClass(obj.object_type)" style="font-size:10px;flex-shrink:0">[[ obj.object_type ]]</span>
                <code class="cp-code" style="flex-shrink:0">[[ obj.table ]]</code>
                <span class="sc-op-desc">[[ obj.desc ]]</span>
                <span class="cp-tag cp-tag-purple" style="font-size:10px;flex-shrink:0">仅提示不删除</span>
              </div>
            </div>
            <div v-else class="sc-expand-note">无多余对象</div>
          </div>
          <div v-if="!r.tables.length" class="sc-expand-note" style="text-align:center;padding:16px 0">两侧结构一致，无差异对象</div>
        </div>
      </div>
    </div>
  </template>

  <!-- ══ 同步 SQL 预览弹窗（多目标按标签页分开显示） ══ -->
  <div v-if="sqlModal.show" class="cp-modal-mask" @click.self="sqlModal.show=false">
    <div class="cp-modal-box" style="width:70vw">
      <div class="cp-modal-header">
        <span>📄 同步 SQL 预览（[[ sqlModal.targets.length ]] 个目标库，共 [[ sqlModalTotal ]] 个对象）</span>
        <button class="cp-modal-close" @click="sqlModal.show=false">✕</button>
      </div>
      <div v-if="sqlModal.targets.length > 1" class="cp-panel-tabs sc-target-tabs">
        <div v-for="st in sqlModal.targets" :key="st.instanceId" class="cp-panel-tab"
             :class="{active: sqlModal.activeId === st.instanceId}" @click="sqlModal.activeId = st.instanceId">
          📥 [[ st.name ]] <span class="cp-tag cp-tag-info" style="font-size:11px">[[ st.tables.length ]]</span>
        </div>
      </div>
      <div class="cp-modal-body" style="padding-bottom:8px">
        <!-- 全部目标的 SQL 面板常驻，切页签只切显隐（高亮 HTML 已在打开弹窗时预计算） -->
        <pre v-for="st in sqlModal.targets" :key="st.instanceId" v-show="st.instanceId === sqlModal.activeId"
             class="sc-sql" style="max-height:none;height:58vh"><code v-html="st.html"></code></pre>
      </div>
      <div class="cp-modal-footer" style="justify-content:space-between">
        <button class="cp-btn cp-btn-outline cp-btn-sm" @click="copySql">复制当前目标 SQL</button>
        <div style="display:flex;gap:10px">
          <button class="cp-btn cp-btn-outline" @click="sqlModal.show=false">关闭</button>
          <button v-if="syncAllowed" class="cp-btn cp-btn-warning" @click="sqlModal.show=false; confirmSyncAll()">执行同步</button>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ 同步确认弹窗（多目标按标签页分开显示） ══ -->
  <div v-if="syncModal.show" class="cp-modal-mask" @click.self="syncModal.show=false">
    <div class="cp-modal-box" style="width:760px">
      <div class="cp-modal-header">
        <span>🚀 表结构同步 · 确认执行</span>
        <button class="cp-modal-close" @click="syncModal.show=false">✕</button>
      </div>
      <div v-if="syncModal.groups.length > 1" class="cp-panel-tabs sc-target-tabs">
        <div v-for="g in syncModal.groups" :key="g.instanceId" class="cp-panel-tab"
             :class="{active: syncModal.activeId === g.instanceId}" @click="syncModal.activeId = g.instanceId">
          📥 [[ g.name ]] <span class="cp-tag cp-tag-warning" style="font-size:11px">[[ g.items.length ]]</span>
        </div>
      </div>
      <div class="cp-modal-body" style="max-height:56vh">
        <div class="cp-modal-warning" style="margin-top:0;margin-bottom:12px">
          ⚠️ 同步将修改<template v-if="projectFilter"> 项目 <b>[[ projectFilter ]]</b> 下</template>
          <b>[[ syncModal.groups.length ]]</b> 个目标库的结构（表/视图/事件），
          DDL 可能造成锁表，请务必在业务低谷期执行。目标多余的对象不会被删除。
        </div>
        <template v-if="activeSyncGroup">
          <div class="sc-sync-group">📥 [[ activeSyncGroup.name ]] · [[ activeSyncGroup.database ]]（[[ activeSyncGroup.items.length ]] 个对象）</div>
          <div class="sc-sync-list" style="max-height:none">
            <div v-for="t in activeSyncGroup.items" :key="t.key">
              <div class="sc-sync-item" style="cursor:pointer" @click="t._showSql = !t._showSql"
                   :title="t._showSql ? '点击收起 SQL' : '点击展开执行 SQL'">
                <span v-if="t.group === 'create'" class="cp-tag cp-tag-danger" style="font-size:11px">创建</span>
                <span v-else class="cp-tag cp-tag-warning" style="font-size:11px">修改</span>
                <span class="cp-tag" :class="typeTagClass(t.object_type)" style="font-size:10px">[[ t.object_type ]]</span>
                <code class="cp-code">[[ t.table ]]</code>
                <span class="sc-op-desc">[[ t.desc ]]</span>
                <span class="cp-tag cp-tag-info" style="font-size:10px;margin-left:auto;flex-shrink:0">[[ t._showSql ? '收起SQL ▲' : '查看SQL ▼' ]]</span>
              </div>
              <pre v-if="t._showSql && t.sqlText" class="sc-sql" style="max-height:220px;margin:4px 0 8px"><code v-html="highlightSql(t.sqlText)"></code></pre>
            </div>
          </div>
        </template>
      </div>
      <div class="cp-modal-footer" style="justify-content:space-between">
        <div style="display:flex;gap:12px;align-items:center">
          <span style="font-size:13px;color:#64748b">共 <b style="color:#d97706">[[ syncModal.total ]]</b> 个对象</span>
          <button class="cp-btn cp-btn-outline cp-btn-sm" @click="toggleAllSql">[[ sqlAllExpanded ? '收起本页全部SQL' : '展开本页全部SQL' ]]</button>
        </div>
        <div style="display:flex;gap:10px">
          <button class="cp-btn cp-btn-outline" @click="syncModal.show=false">取消</button>
          <button class="cp-btn cp-btn-danger" @click="executeSync" :disabled="syncModal.loading">
            [[ syncModal.loading ? '提交中...' : '确认同步' ]]
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- ══ 同步日志弹框（SSE 实时推送） ══ -->
  <div v-if="syncLogVisible" class="cp-modal-mask">
    <div class="cp-modal-box" style="width:65vw">
      <div class="cp-modal-header">
        <span>🚀 [[ syncLogTitle ]]</span>
        <button class="cp-modal-close" @click="syncLogVisible=false">✕</button>
      </div>
      <div class="cp-plog" ref="syncLogContainer">
        <div v-for="(log, i) in syncLogs" :key="i" class="cp-plog-line">
          <span class="cp-plog-time">[[ log.time || '' ]]</span>
          <span v-if="log.op" class="cp-plog-op">[[ log.op ]]</span>
          <span v-if="log.source" class="cp-plog-src">[[ log.source ]]</span>
          <span v-if="log.database && log.database !== '-'" class="cp-plog-db">[[ log.database ]]</span>
          <span :class="'cp-plog-msg cp-plog-lvl-' + (log.level || 'info').toLowerCase()">[[ log.message || '' ]]</span>
        </div>
        <div v-if="syncLogDone" class="cp-plog-line">
          <span :class="'cp-plog-msg cp-plog-lvl-' + (syncLogSuccess ? 'done' : 'failed')">[[ syncLogSuccess ? '=== 同步完成 ===' : '=== 同步失败 ===' ]]</span>
        </div>
      </div>
      <div class="cp-modal-footer" style="justify-content:flex-end">
        <button class="cp-btn cp-btn-outline" @click="syncLogVisible=false">关闭</button>
      </div>
    </div>
  </div>
</div>
`,

  data() {
    return {
      // 实例与库选择（目标只选实例，库名与源一致）
      instances: [],
      projectFilter: '',
      sourceInstanceId: '',
      targetInstanceIds: [],
      sourceDbs: [],
      sourceDb: '',
      loadingSourceDbs: false,
      // 对比结果（每个目标一个结果），多目标时用标签页切换
      comparing: false,
      compared: false,
      compareResults: [],
      activeTargetId: '',
      // 勾选同步：key 为 目标实例id|对象key
      selectedKeys: {},
      // 过滤
      typeFilter: 'all',
      tableFilter: '',
      // 弹窗
      sqlModal: { show: false, targets: [], activeId: '' },
      syncModal: { show: false, loading: false, groups: [], total: 0, activeId: '' },
      // 同步日志（SSE）
      syncLogVisible: false,
      syncLogTitle: '',
      syncLogs: [],
      syncLogDone: false,
      syncLogSuccess: false,
      syncEventSource: null,
    };
  },

  computed: {
    instanceOptions() {
      // 选中项目后，源/目标均只展示该项目的实例（正常不会跨项目同步对比）
      const list = this.projectFilter
        ? this.instances.filter(i => i.project === this.projectFilter)
        : this.instances;
      return list.map(i => ({
        id: String(i.id),
        label: `${i.name}（${i.host}:${i.port}）`,
      }));
    },
    // 源下拉：排除已被选为目标的实例（已选的不在左侧显示）
    sourceInstanceOptions() {
      const used = new Set(this.targetInstanceIds);
      return this.instanceOptions.filter(i => !used.has(i.id));
    },
    // 目标下拉：排除已被选为源的实例
    targetInstanceOptions() {
      return this.instanceOptions.filter(i => i.id !== this.sourceInstanceId);
    },
    projectOptions() {
      return [...new Set(this.instances.map(i => i.project).filter(Boolean))].sort();
    },
    canCompare() {
      return this.sourceInstanceId && this.sourceDb && this.targetInstanceIds.length > 0;
    },
    // 当前标签页对应的对比结果
    activeResult() {
      if (!this.compareResults.length) return null;
      return this.compareResults.find(r => r.target.instance_id === this.activeTargetId)
        || this.compareResults[0];
    },
    typeTabs() {
      const s = { missing: 0, diff: 0, extra: 0 };
      for (const r of this.compareResults) {
        for (const k of Object.keys(s)) s[k] += r.summary[k] || 0;
      }
      return [
        { key: 'all', label: '全部', count: 0 },
        { key: 'create', label: '➕ 创建', count: s.missing },
        { key: 'modify', label: '✏️ 修改', count: s.diff },
        { key: 'drop', label: '🗑️ 删除', count: s.extra },
      ];
    },
    needSyncCount() {
      let n = 0;
      for (const r of this.compareResults) {
        n += r.tables.filter(t => t.group === 'create' || t.group === 'modify').length;
      }
      return n;
    },
    // 已勾选待同步的对象数（跨全部目标）
    selectedCount() {
      return Object.values(this.selectedKeys).filter(Boolean).length;
    },
    // 同步弹窗内当前页签 SQL 是否已全部展开
    sqlAllExpanded() {
      const g = this.activeSyncGroup;
      return !!g && g.items.every(t => t._showSql || !t.sqlText);
    },
    // SQL 预览弹窗：当前页签对应的目标 SQL
    activeSqlTarget() {
      if (!this.sqlModal.targets.length) return null;
      return this.sqlModal.targets.find(t => t.instanceId === this.sqlModal.activeId)
        || this.sqlModal.targets[0];
    },
    sqlModalTotal() {
      return this.sqlModal.targets.reduce((s, t) => s + t.tables.length, 0);
    },
    // 同步确认弹窗：当前页签对应的目标分组
    activeSyncGroup() {
      if (!this.syncModal.groups.length) return null;
      return this.syncModal.groups.find(g => g.instanceId === this.syncModal.activeId)
        || this.syncModal.groups[0];
    },
    syncAllowed() {
      return this.$auth && this.$auth.hasPermission('op:structure_sync');
    }
  },

  methods: {
    instanceLabel(id) {
      const inst = this.instances.find(i => String(i.id) === id);
      return inst ? inst.name : id;
    },

    // ── 加载实例 ──
    loadInstances() {
      ajax('GET', '/api/database/instances', null, (res) => {
        if (res.code === 200) {
          const data = res.data || {};
          this.instances = Array.isArray(data) ? data : [...(data.auto || []), ...(data.custom || [])];
        } else {
          ElementPlus.ElMessage.error(res.msg || '获取实例失败');
        }
      });
    },

    loadDatabases(instanceId) {
      if (!instanceId) return;
      this.loadingSourceDbs = true;
      ajax('GET', `/api/database/databases?instance_id=${instanceId}`, null, (res) => {
        this.loadingSourceDbs = false;
        if (res.code === 200) {
          this.sourceDbs = (res.data || []).map(d => d.SCHEMA_NAME);
        } else {
          ElementPlus.ElMessage.error(res.msg || '获取数据库列表失败');
        }
      });
    },

    onSourceInstanceChange(id) {
      this.sourceDb = '';
      this.sourceDbs = [];
      this.loadDatabases(id);
    },

    // 目标多选变化：目标不再单独选库，对比时直接用源库名
    onTargetInstancesChange() {},

    // 点选项目：再次点击已选项目取消选择；选中后清理不在项目内的源/目标
    selectProject(project) {
      this.projectFilter = (project && this.projectFilter === project) ? '' : project;
      this.onProjectChange();
    },

    // 切换项目：源/目标只保留该项目实例，不在项目内的选择清空
    onProjectChange() {
      const valid = new Set(this.instanceOptions.map(i => i.id));
      if (this.sourceInstanceId && !valid.has(this.sourceInstanceId)) {
        this.sourceInstanceId = '';
        this.sourceDb = '';
        this.sourceDbs = [];
      }
      const kept = this.targetInstanceIds.filter(id => valid.has(id));
      if (kept.length !== this.targetInstanceIds.length) {
        this.targetInstanceIds = kept;
      }
    },

    // 交换源/目标：仅单目标时可用（库名两侧一致，直接互换实例）
    swapSides() {
      if (this.targetInstanceIds.length !== 1 || !this.sourceInstanceId) {
        ElementPlus.ElMessage.warning('仅在单目标时可交换源/目标');
        return;
      }
      const srcId = this.sourceInstanceId;
      const tgtId = this.targetInstanceIds[0];
      this.sourceInstanceId = tgtId;
      this.targetInstanceIds = [srcId];
      // 重新加载源实例的库列表
      this.sourceDbs = [];
      this.sourceDb = '';
      this.loadDatabases(tgtId);
    },

    // ── 对比（一源多目标：目标库名与源一致，逐目标对比） ──
    doCompare() {
      if (!this.sourceInstanceId || !this.sourceDb || !this.targetInstanceIds.length) return;
      const targets = [...this.targetInstanceIds];
      this.comparing = true;
      this.compared = false;
      this.compareResults = [];
      this.activeTargetId = '';
      this.selectedKeys = {};
      const srcInstanceId = this.sourceInstanceId;
      const srcDb = this.sourceDb;
      let done = 0;
      targets.forEach(t => {
        const body = {
          project: this.projectFilter || '',
          source_instance_id: srcInstanceId,
          target_instance_id: t,
          source_database: srcDb,
          target_database: srcDb,
        };
        ajax('POST', '/api/database/compare_structure', body, (res) => {
          done++;
          if (res.code === 200) {
            this.compareResults.push(res.data);
            // 按目标选择顺序展示
            this.compareResults.sort((a, b) =>
              targets.indexOf(a.target.instance_id) - targets.indexOf(b.target.instance_id));
            if (!this.activeTargetId) this.activeTargetId = this.compareResults[0].target.instance_id;
          } else {
            ElementPlus.ElMessage.error(`${this.instanceLabel(t)} 对比失败：${res.msg || '未知错误'}`);
          }
          if (done === targets.length) {
            this.comparing = false;
            if (this.compareResults.length) this.compared = true;
          }
        });
      });
    },

    // 按分类取指定目标的对象列表（group 由后端计算，受搜索关键字过滤）
    groupObjects(group, r) {
      let objs = r.tables;
      const kw = this.tableFilter.trim().toLowerCase();
      if (kw) objs = objs.filter(o => o.table.toLowerCase().includes(kw));
      return objs.filter(o => o.group === group);
    },

    typeTagClass(objectType) {
      return ({ '表': 'cp-tag-info', '视图': 'cp-tag-success', '事件': 'cp-tag-purple' })[objectType] || 'cp-tag-info';
    },

    // SQL 语法高亮（注释/字符串/关键字/数字，输出 hljs-* 类名）
    highlightSql(sql) {
      if (!sql) return '';
      const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const kwRe = /\b(CREATE|ALTER|DROP|TABLE|VIEW|EVENT|ADD|MODIFY|CHANGE|COLUMN|INDEX|KEY|PRIMARY|UNIQUE|IF|NOT|EXISTS|DEFAULT|COMMENT|ENGINE|CHARSET|CHARACTER|COLLATE|AUTO_INCREMENT|AFTER|FIRST|UNSIGNED|NULL|ON|UPDATE|CURRENT_TIMESTAMP|USING|BTREE|FULLTEXT|ASC|DESC|DEFINER|SCHEDULE|EVERY|STARTS|ENDS|DO|BEGIN|END)\b/gi;
      const decorate = seg => esc(seg).replace(kwRe, '<span class="hljs-keyword">$1</span>')
                                       .replace(/\b(\d+)\b/g, '<span class="hljs-number">$1</span>');
      // 先按 注释/字符串/反引号标识符 切分，避免对其内部做关键字替换
      const tokenRe = /(--[^\n]*|#[^\n]*|'(?:[^'\\]|\\.|'')*'|`[^`]*`)/g;
      let html = '', last = 0, m;
      while ((m = tokenRe.exec(sql)) !== null) {
        html += decorate(sql.slice(last, m.index));
        const t = m[1];
        if (t.startsWith('--') || t.startsWith('#')) html += '<span class="hljs-comment">' + esc(t) + '</span>';
        else html += '<span class="hljs-string">' + esc(t) + '</span>';
        last = m.index + t.length;
      }
      html += decorate(sql.slice(last));
      return html;
    },

    // ── SQL 预览（每个目标单独一份 SQL，弹窗内标签页切换） ──
    viewSyncSql() {
      const targets = [];
      for (const r of this.compareResults) {
        const need = r.tables.filter(t => t.group === 'create' || t.group === 'modify');
        if (!need.length) continue;
        const lines = [
          `-- 源：${r.source.name} · ${r.source.database} → 目标：${r.target.name} · ${r.target.database}`
        ];
        const tables = [];
        for (const t of need) {
          const sqls = Array.isArray(t.sql) ? t.sql : (t.sql ? [t.sql] : []);
          if (!sqls.length) continue;
          lines.push('', `-- ${t.group === 'create' ? '创建' : '修改'}${t.object_type || '表'} ${t.table}`);
          lines.push(...sqls.map(s => s.trim().replace(/;+$/, '') + ';'));
          tables.push(t.table);
        }
        targets.push({
          instanceId: r.target.instance_id,
          name: r.target.name,
          database: r.target.database,
          sql: lines.join('\n'),
          tables,
          html: this.highlightSql(lines.join('\n')),  // 预计算高亮，切页签不再重新计算
        });
      }
      if (!targets.length) {
        ElementPlus.ElMessage.success('两侧结构一致，无同步 SQL');
        return;
      }
      this.sqlModal = { show: true, targets, activeId: targets[0].instanceId };
    },

    copySql() {
      const text = this.activeSqlTarget ? this.activeSqlTarget.sql : '';
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => ElementPlus.ElMessage.success('已复制当前目标 SQL'));
      } else {
        ElementPlus.ElMessage.warning('当前环境不支持复制');
      }
    },

    // ── 勾选同步 ──
    isObjSelected(r, obj) {
      return !!this.selectedKeys[`${r.target.instance_id}|${obj.key}`];
    },

    toggleObjSelect(r, obj, checked) {
      const k = `${r.target.instance_id}|${obj.key}`;
      const m = { ...this.selectedKeys };
      if (checked) m[k] = true; else delete m[k];
      this.selectedKeys = m;
    },

    selectAllSync() {
      const m = { ...this.selectedKeys };
      for (const r of this.compareResults) {
        for (const t of r.tables) {
          if (t.group === 'create' || t.group === 'modify') {
            m[`${r.target.instance_id}|${t.key}`] = true;
          }
        }
      }
      this.selectedKeys = m;
    },

    clearSelection() {
      this.selectedKeys = {};
    },

    // ── 分类整组勾选 ──
    // 指定目标下该分类的可同步对象 key 列表（创建/修改）
    syncableRowsOfGroup(group, r) {
      if (!r || group === 'drop') return [];
      const tid = r.target.instance_id;
      return r.tables
        .filter(t => t.group === group)
        .map(t => `${tid}|${t.key}`);
    },

    isGroupAllSelected(group, r) {
      const keys = this.syncableRowsOfGroup(group, r);
      return keys.length > 0 && keys.every(k => this.selectedKeys[k]);
    },

    isGroupIndeterminate(group, r) {
      const keys = this.syncableRowsOfGroup(group, r);
      const n = keys.filter(k => this.selectedKeys[k]).length;
      return n > 0 && n < keys.length;
    },

    toggleGroupSelect(group, checked, r) {
      const m = { ...this.selectedKeys };
      for (const k of this.syncableRowsOfGroup(group, r)) {
        if (checked) m[k] = true; else delete m[k];
      }
      this.selectedKeys = m;
    },

    // ── 同步执行（多目标一次提交） ──
    // 构建同步弹窗的目标分组；onlySelected=true 时仅包含已勾选对象
    buildSyncGroups(onlySelected) {
      const groups = [];
      for (const r of this.compareResults) {
        let items = r.tables.filter(t => t.group === 'create' || t.group === 'modify');
        if (onlySelected) {
          items = items.filter(t => this.selectedKeys[`${r.target.instance_id}|${t.key}`]);
        }
        if (!items.length) continue;
        groups.push({
          instanceId: r.target.instance_id, name: r.target.name, database: r.target.database,
          items: items.map(t => {
            const sqls = Array.isArray(t.sql) ? t.sql : (t.sql ? [t.sql] : []);
            return { ...t, _showSql: false,
                     sqlText: sqls.map(s => s.trim().replace(/;+$/, '') + ';').join('\n') };
          }),
        });
      }
      return groups;
    },

    openSyncModal(groups) {
      this.syncModal = { show: true, loading: false, groups,
                         total: groups.reduce((s, g) => s + g.items.length, 0),
                         activeId: groups[0] ? groups[0].instanceId : '' };
    },

    confirmSyncAll() {
      const groups = this.buildSyncGroups(false);
      if (!groups.length) {
        ElementPlus.ElMessage.success('两侧结构一致，无需同步');
        return;
      }
      this.openSyncModal(groups);
    },

    syncSelected() {
      const groups = this.buildSyncGroups(true);
      if (!groups.length) {
        ElementPlus.ElMessage.warning('请先勾选需要同步的对象');
        return;
      }
      this.openSyncModal(groups);
    },

    // 展开/收起当前页签内全部对象的执行 SQL
    toggleAllSql() {
      const g = this.activeSyncGroup;
      if (!g) return;
      const anyHidden = g.items.some(t => !t._showSql && t.sqlText);
      for (const t of g.items) t._showSql = anyHidden;
    },

    executeSync() {
      this.syncModal.loading = true;
      const body = {
        project: this.projectFilter || '',
        source_instance_id: this.sourceInstanceId,
        source_database: this.sourceDb,
        targets: this.syncModal.groups.map(g => ({
          instance_id: g.instanceId,
          database: this.sourceDb,
          tables: g.items.map(t => t.table),
        })),
      };
      const project = this.projectFilter ? `[${this.projectFilter}] ` : '';
      const title = `结构同步 ${project}${this.sourceDb} → ${this.syncModal.groups.length} 个目标库`;
      ajax('POST', '/api/database/sync_structure_async', body, (res) => {
        this.syncModal.loading = false;
        this.syncModal.show = false;
        if (res.code === 200) {
          this.selectedKeys = {};
          this.openSyncLog(title, res.data.task_key);
        } else {
          ElementPlus.ElMessage.error(res.msg || '同步任务提交失败');
        }
      });
    },

    // ── 同步日志（SSE，复用排序修正日志流） ──
    openSyncLog(title, taskKey) {
      this.syncLogTitle = title;
      this.syncLogs = [];
      this.syncLogDone = false;
      this.syncLogSuccess = false;
      this.syncLogVisible = true;
      this.closeSyncSSE();
      const self = this;
      const token = localStorage.getItem('auth_token') || '';
      const es = new EventSource('/api/database/stream?task_key=' + encodeURIComponent(taskKey) + '&token=' + encodeURIComponent(token));
      this.syncEventSource = es;
      es.onmessage = function(e) {
        const d = JSON.parse(e.data);
        if (d.done) {
          self.syncLogDone = true;
          self.syncLogSuccess = d.success !== false;
          es.close();
          self.syncEventSource = null;
          // 同步结束后自动重新对比刷新结果
          self.doCompare();
          return;
        }
        self.syncLogs.push(d);
        self.$nextTick(() => {
          const c = self.$refs.syncLogContainer;
          if (c) c.scrollTop = c.scrollHeight;
        });
      };
      es.onerror = function() {
        es.close();
        self.syncEventSource = null;
        if (!self.syncLogDone) {
          self.syncLogDone = true;
          self.syncLogSuccess = false;
          self.syncLogs.push({ level: 'ERROR', message: 'SSE连接失败，无法获取同步进度', time: '' });
        }
      };
    },

    closeSyncSSE() {
      if (this.syncEventSource) {
        this.syncEventSource.close();
        this.syncEventSource = null;
      }
    }
  },

  created() {
    this.loadInstances();
  },

  beforeUnmount() {
    this.closeSyncSSE();
  }
};
