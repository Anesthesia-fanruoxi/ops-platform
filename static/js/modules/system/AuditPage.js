// 审计日志：平台管理操作轨迹查询（动作级 + 字段级 diff）
const AuditPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
  <div class="audit-page">
    <!-- 筛选栏 -->
    <el-card shadow="never" class="audit-filter-card">
      <div class="audit-filter">
        <el-input v-model="query.username" placeholder="操作用户" clearable size="small" style="width:160px" @keyup.enter="load(1)" />
        <el-select v-model="query.module" placeholder="模块" clearable size="small" style="width:150px">
          <el-option v-for="m in modules" :key="m" :label="m" :value="m" />
        </el-select>
        <el-input v-model="query.action" placeholder="动作" clearable size="small" style="width:130px" @keyup.enter="load(1)" />
        <el-select v-model="query.result" placeholder="结果" clearable size="small" style="width:120px">
          <el-option label="成功" value="success" />
          <el-option label="拒绝" value="denied" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-date-picker v-model="query.timeRange" type="datetimerange" size="small"
                        range-separator="至" start-placeholder="开始时间" end-placeholder="结束时间"
                        style="width:360px" value-format="YYYY-MM-DD HH:mm:ss" />
        <el-button type="primary" size="small" @click="load(1)">查询</el-button>
        <el-button size="small" @click="reset">重置</el-button>
      </div>
    </el-card>

    <!-- 列表 -->
    <el-card shadow="never">
      <el-table :data="list" v-loading="loading" border stripe
                :header-cell-style="{background:'#f5f7fa',fontWeight:'bold'}">
        <el-table-column prop="created_at" label="时间" width="190" />
        <el-table-column prop="username" label="用户" width="150" show-overflow-tooltip>
          <template #default="s">[[ s.row.username || '-' ]]</template>
        </el-table-column>
        <el-table-column prop="module" label="模块" width="130" align="center" />
        <el-table-column prop="action" label="动作" width="140" align="center" />
        <el-table-column label="结果" width="110" align="center">
          <template #default="s">
            <el-tag :type="s.row.result === 'success' ? 'success' : (s.row.result === 'denied' ? 'warning' : 'danger')">[[ s.row.result ]]</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="160" />
        <el-table-column prop="latency_ms" label="耗时(ms)" width="120" align="center" />
        <el-table-column label="描述" min-width="280" show-overflow-tooltip>
          <template #default="s">[[ s.row.detail || s.row.path || '-' ]]</template>
        </el-table-column>
        <el-table-column label="操作" width="110" align="center">
          <template #default="s">
            <el-button link type="primary" @click="showDetail(s.row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="audit-pager">
        <el-pagination background layout="total, prev, pager, next" :total="total"
                       :page-size="query.page_size" :current-page="query.page"
                       @current-change="load" />
      </div>
    </el-card>

    <!-- 详情弹窗 -->
    <el-dialog v-model="detailVisible" title="审计详情" width="760px" class="audit-dialog" :close-on-click-modal="false">
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="时间">[[ row.created_at ]]</el-descriptions-item>
        <el-descriptions-item label="用户">[[ row.username || '-' ]]</el-descriptions-item>
        <el-descriptions-item label="结果">
          <el-tag size="small" :type="row.result === 'success' ? 'success' : 'danger'">[[ row.result ]]</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="模块">[[ row.module ]]</el-descriptions-item>
        <el-descriptions-item label="动作">[[ row.action ]]</el-descriptions-item>
        <el-descriptions-item label="耗时">[[ row.latency_ms ]] ms</el-descriptions-item>
        <el-descriptions-item label="IP" :span="2">[[ row.ip || '-' ]]</el-descriptions-item>
        <el-descriptions-item label="路径">[[ row.path || '-' ]]</el-descriptions-item>
        <el-descriptions-item label="描述" :span="3">[[ row.detail || '-' ]]</el-descriptions-item>
      </el-descriptions>

      <template v-if="row.params">
        <div class="audit-sec-title">请求参数（脱敏）</div>
        <pre class="audit-pre">[[ fmtJson(row.params) ]]</pre>
      </template>

      <template v-if="row.diff">
        <div class="audit-sec-title">字段变更（字段级 diff）</div>
        <el-table :data="diffRows" size="small" border stripe>
          <el-table-column prop="field" label="字段" width="200" />
          <el-table-column label="旧值" min-width="200">
            <template #default="s"><span class="audit-old">[[ fmtVal(s.row.old) ]]</span></template>
          </el-table-column>
          <el-table-column label="新值" min-width="200">
            <template #default="s"><span class="audit-new">[[ fmtVal(s.row.new) ]]</span></template>
          </el-table-column>
        </el-table>
      </template>

      <div style="text-align:right;margin-top:12px">
        <el-button size="small" @click="detailVisible = false">关闭</el-button>
      </div>
    </el-dialog>
  </div>`,
  data() {
    return {
      query: { username: '', module: '', action: '', result: '', timeRange: null, page: 1, page_size: 20 },
      modules: [],
      list: [],
      total: 0,
      loading: false,
      detailVisible: false,
      row: {},
      diffRows: [],
    };
  },
  mounted() {
    this.loadModules();
    this.load(1);
  },
  methods: {
    load(page) {
      if (page) this.query.page = page;
      this.loading = true;
      const p = new URLSearchParams({
        page: String(this.query.page),
        page_size: String(this.query.page_size),
      });
      if (this.query.username) p.set('username', this.query.username);
      if (this.query.module) p.set('module', this.query.module);
      if (this.query.action) p.set('action', this.query.action);
      if (this.query.result) p.set('result', this.query.result);
      if (this.query.timeRange && this.query.timeRange.length === 2) {
        p.set('start_time', this.query.timeRange[0]);
        p.set('end_time', this.query.timeRange[1]);
      }
      ajax('GET', '/api/audit/list?' + p.toString(), null, res => {
        this.loading = false;
        if (res.code === 200) {
          this.list = res.data.list || [];
          this.total = res.data.total || 0;
        } else {
          ElementPlus.ElMessage.error(res.msg || '加载失败');
        }
      });
    },
    loadModules() {
      ajax('GET', '/api/audit/modules', null, res => {
        if (res.code === 200) {
          this.modules = (res.data && res.data.modules) || [];
        }
      });
    },
    reset() {
      this.query = { username: '', module: '', action: '', result: '', timeRange: null, page: 1, page_size: 20 };
      this.load(1);
    },
    showDetail(row) {
      this.row = row;
      this.diffRows = [];
      if (row.diff && typeof row.diff === 'object') {
        this.diffRows = Object.keys(row.diff).map(k => ({ field: k, old: row.diff[k].old, new: row.diff[k].new }));
      }
      this.detailVisible = true;
    },
    fmtJson(obj) {
      try { return JSON.stringify(obj, null, 2); } catch (e) { return String(obj); }
    },
    fmtVal(v) {
      if (v === null || v === undefined) return '-';
      if (typeof v === 'object') { try { return JSON.stringify(v); } catch (e) { return String(v); } }
      return String(v);
    },
  },
};

// ── 样式 ──
(function () {
  const css = `
.audit-page { padding: 4px 2px; }
.audit-filter-card { margin-bottom: 16px; }
.audit-filter { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.audit-pager { margin-top: 12px; display: flex; justify-content: flex-end; }
.audit-sec-title { font-size: 13px; font-weight: 600; color: #303133; margin: 16px 0 8px; }
.audit-pre { background: #0a2e3c; color: #a8bcc0; padding: 12px; border-radius: 6px; font-size: 12px; overflow: auto; max-height: 260px; font-family: Consolas, Menlo, monospace; }
.audit-old { color: #f56c6c; }
.audit-new { color: #67c23a; }
.el-overlay:has(.audit-dialog) { display: flex; align-items: center; justify-content: center; }
.audit-dialog .el-dialog { margin: 0 !important; }
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
})();
