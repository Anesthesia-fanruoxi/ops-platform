// 多仓发版：批次总览 + 服务行进度 + 单服务步骤/日志
const MultiBuildPage = {
  name: 'MultiBuildPage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
  <div class="card multi-build-page">
    <div class="page-header">
      <div class="section-title">多仓发版</div>
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:12px;color:#909399">一个批次一次多仓发版，服务行可查看各自步骤</span>
        <el-button size="small" @click="refreshCurrent">刷新</el-button>
      </div>
    </div>

    <!-- 批次列表 -->
    <div v-if="!selectedBatch" v-loading="batchLoading">
      <el-table v-if="batches.length" :data="batches" stripe border size="small" style="width:100%" @row-click="openBatch">
        <el-table-column prop="batch_no" label="批次编号" min-width="190" />
        <el-table-column label="项目 / 环境" min-width="170">
          <template #default="s">[[ s.row.project_name ]] / [[ s.row.environment_name ]]</template>
        </el-table-column>
        <el-table-column prop="branch" label="分支" min-width="130" show-overflow-tooltip />
        <el-table-column label="服务" width="80" align="center"><template #default="s">[[ s.row.total_services ]]</template></el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="s"><el-tag :type="statusType(s.row.status)" size="small">[[ statusText(s.row.status) ]]</el-tag></template>
        </el-table-column>
        <el-table-column label="成功 / 失败 / 运行" width="150" align="center">
          <template #default="s">
            <span style="color:#67c23a">[[ s.row.build_status_counts.success ]]</span> /
            <span style="color:#f56c6c">[[ s.row.build_status_counts.failed ]]</span> /
            <span style="color:#409eff">[[ s.row.build_status_counts.running + s.row.build_status_counts.pending ]]</span>
          </template>
        </el-table-column>
        <el-table-column prop="triggered_by" label="执行人" width="90" align="center" />
        <el-table-column prop="created_at" label="创建时间" width="165" />
        <el-table-column label="操作" width="80" align="center">
          <template #default="s"><el-button link type="primary" size="small" @click.stop="openBatch(s.row)">查看</el-button></template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无多仓发版批次" :image-size="70" />
    </div>

    <!-- 批次详情 -->
    <div v-else class="multi-batch-detail">
      <div class="multi-batch-back">
        <el-button link type="primary" size="small" @click="backToList">← 返回批次列表</el-button>
      </div>
      <div class="multi-batch-summary">
        <div class="mb-title">
          <span>[[ selectedBatch.batch_no ]]</span>
          <el-tag :type="statusType(selectedBatch.status)" size="small">[[ statusText(selectedBatch.status) ]]</el-tag>
        </div>
        <div class="mb-meta">
          <span>项目/环境 <b>[[ selectedBatch.project_name ]] / [[ selectedBatch.environment_name ]]</b></span>
          <span>分支 <b>[[ selectedBatch.branch ]]</b></span>
          <span>服务 <b>[[ selectedBatch.total_services ]]</b></span>
          <span>仓库 <b>[[ selectedBatch.total_builds ]]</b></span>
          <span>执行人 <b>[[ selectedBatch.triggered_by || '-' ]]</b></span>
          <span>开始 <b>[[ selectedBatch.created_at || '-' ]]</b></span>
        </div>
        <div class="mb-counts">
          <span class="mb-count ok">成功 [[ serviceCounts.success ]]</span>
          <span class="mb-count run">运行/排队 [[ serviceCounts.running ]]</span>
          <span class="mb-count bad">失败 [[ serviceCounts.failed ]]</span>
        </div>
      </div>

      <el-table :data="services" size="small" border stripe style="width:100%" highlight-current-row
                :row-class-name="serviceRowClass" @row-click="selectService">
        <el-table-column label="仓库" min-width="180">
          <template #default="s"><span class="mb-repo">[[ s.row.repo_name ]]</span></template>
        </el-table-column>
        <el-table-column label="服务" min-width="150">
          <template #default="s"><span class="mb-service">[[ s.row.service_name ]]</span></template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="s"><el-tag :type="statusType(s.row.status)" size="small">[[ statusText(s.row.status) ]]</el-tag></template>
        </el-table-column>
        <el-table-column label="进度" min-width="180">
          <template #default="s">
            <div class="mb-progress"><div class="mb-progress-track"><div :class="['mb-progress-bar', s.row.status]" :style="{width: Math.max(0, Math.min(100, s.row.progress || 0)) + '%'}"></div></div></div>
            <div class="mb-progress-text">[[ s.row.current_step || (s.row.status === 'pending' ? '等待执行槽' : '') ]] [[ s.row.progress || 0 ]]%</div>
          </template>
        </el-table-column>
        <el-table-column prop="agent_name" label="执行节点" width="110" />
        <el-table-column label="耗时" width="80" align="center">
          <template #default="s">[[ s.row.duration ? Math.round(s.row.duration) + 's' : '-' ]]</template>
        </el-table-column>
        <el-table-column label="操作" width="90" align="center">
          <template #default="s"><el-button link type="primary" size="small" @click.stop="selectService(s.row)">查看详情</el-button></template>
        </el-table-column>
      </el-table>

      <div v-if="selectedService" class="mb-service-detail">
        <div class="mb-detail-head">
          <div>
            <div class="mb-detail-title">[[ selectedService.service_name ]]</div>
            <div class="mb-detail-sub">[[ selectedService.repo_name ]] · [[ selectedService.branch ]] · 点击服务行查看步骤</div>
          </div>
          <el-tag :type="statusType(selectedService.status)" size="small">[[ statusText(selectedService.status) ]]</el-tag>
        </div>
        <div class="mb-steps">
          <div v-for="st in detailSteps" :key="st.step_no" :class="['mb-step', st.status]">
            <div class="mb-step-dot">[[ st.status === 'success' ? '✓' : st.status === 'failed' ? '!' : st.step_no ]]</div>
            <span>[[ st.name ]]</span>
          </div>
          <span v-if="!detailSteps.length" class="mb-muted">步骤状态加载中...</span>
        </div>
        <div v-if="selectedService.error" class="mb-error">[[ selectedService.error ]]</div>
        <div class="mb-log" ref="mbLog">[[ detailLog || '暂无日志' ]]</div>
      </div>
    </div>
  </div>
  `,
  data() {
    return {
      batches: [], batchLoading: false,
      selectedBatch: null, services: [],
      selectedService: null, detailSteps: [], detailLog: '',
      stepEs: null, logEs: null, pollTimer: null,
    };
  },
  computed: {
    serviceCounts() {
      const c = { success: 0, failed: 0, running: 0, pending: 0, cancelled: 0 };
      this.services.forEach(s => { c[s.status] = (c[s.status] || 0) + 1; });
      return c;
    },
  },
  methods: {
    statusType(s) { return s === 'success' ? 'success' : s === 'failed' ? 'danger' : s === 'running' ? 'primary' : 'info'; },
    statusText(s) { return { pending: '等待中', running: '运行中', success: '成功', failed: '失败', cancelled: '已取消' }[s] || s || '-'; },
    serviceRowClass({ row }) {
      return this.selectedService && this.selectedService.build_id === row.build_id
        && this.selectedService.service_name === row.service_name ? 'mb-row-active' : '';
    },
    loadBatches() {
      this.batchLoading = true;
      let url = '/api/cicd/multi-templates/batches';
      const q = this.$route.query || {};
      const params = [];
      if (q.project_id) params.push('project_id=' + encodeURIComponent(q.project_id));
      if (q.environment_id) params.push('environment_id=' + encodeURIComponent(q.environment_id));
      if (params.length) url += '?' + params.join('&');
      ajax('GET', url, null, (res) => {
        this.batchLoading = false;
        if (res.code === 200) {
          this.batches = res.data || [];
          if (q.batch) {
            const b = this.batches.find(x => String(x.id) === String(q.batch) || x.batch_no === q.batch);
            if (b) this.openBatch(b);
          }
        }
      }, () => { this.batchLoading = false; });
    },
    openBatch(row) {
      this.selectedBatch = row; this.services = []; this.selectedService = null;
      this.loadBatchDetail();
      this.stopPoll();
      this.pollTimer = setInterval(() => {
        if (!this.selectedBatch || ['success', 'failed', 'cancelled'].includes(this.selectedBatch.status)) { this.stopPoll(); return; }
        this.loadBatchDetail(true);
      }, 3000);
    },
    loadBatchDetail(silent) {
      if (!this.selectedBatch) return;
      ajax('GET', '/api/cicd/multi-templates/batches/' + this.selectedBatch.id, null, (res) => {
        if (res.code === 200 && res.data) {
          this.selectedBatch = res.data;
          this.services = res.data.services || [];
          if (this.selectedService) {
            const cur = this.services.find(x => x.build_id === this.selectedService.build_id && x.service_name === this.selectedService.service_name);
            if (cur) this.selectedService = cur;
          }
        }
      }, () => { if (!silent) showError('批次详情加载失败'); });
    },
    refreshCurrent() {
      if (this.selectedBatch) this.loadBatchDetail();
      else this.loadBatches();
    },
    backToList() {
      this.stopAll();
      this.selectedBatch = null;
      this.services = [];
      this.selectedService = null;
      const q = Object.assign({}, this.$route.query);
      if (q.batch) {
        delete q.batch;
        this.$router.replace({ path: '/multi-build', query: q });
        return;
      }
      this.loadBatches();
    },
    selectService(row) {
      this.selectedService = row; this.detailSteps = []; this.detailLog = '';
      this.disconnectDetail();
      ajax('GET', '/api/cicd/builds/' + row.build_id + '/steps', null, (res) => {
        if (res.code === 200 && res.data) this.detailSteps = res.data.steps || [];
      });
      this.connectSteps(row.build_id);
      this.connectLog(row.build_id);
    },
    connectSteps(buildId) {
      const token = localStorage.getItem('auth_token') || '';
      const es = new EventSource('/api/cicd/builds/' + buildId + '/steps/stream?token=' + encodeURIComponent(token));
      this.stepEs = es;
      es.onmessage = (evt) => {
        try {
          const d = JSON.parse(evt.data);
          if (d.steps) this.detailSteps = d.steps;
          if (d.done) { es.close(); this.stepEs = null; }
        } catch (e) {}
      };
      es.onerror = () => { es.close(); this.stepEs = null; };
    },
    connectLog(buildId) {
      const token = localStorage.getItem('auth_token') || '';
      const es = new EventSource('/api/cicd/builds/' + buildId + '/log?type=all&follow=true&token=' + encodeURIComponent(token));
      this.logEs = es;
      es.onmessage = (evt) => {
        try {
          const d = JSON.parse(evt.data);
          if (d.text) {
            this.detailLog += d.text;
            this.$nextTick(() => { const el = this.$refs.mbLog; if (el) el.scrollTop = el.scrollHeight; });
          }
        } catch (e) {}
      };
      es.onerror = () => { es.close(); this.logEs = null; };
    },
    disconnectDetail() {
      if (this.stepEs) { this.stepEs.close(); this.stepEs = null; }
      if (this.logEs) { this.logEs.close(); this.logEs = null; }
    },
    stopPoll() { if (this.pollTimer) { clearInterval(this.pollTimer); this.pollTimer = null; } },
    stopAll() { this.stopPoll(); this.disconnectDetail(); },
  },
  watch: {
    '$route.query.batch'() { this.loadBatches(); },
  },
  mounted() { this.loadBatches(); },
  beforeUnmount() { this.stopAll(); },
};
