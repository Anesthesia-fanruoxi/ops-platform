// 监控信息：SSE 实时展示平台多维度健康检查（数据库/Redis/线程池/异步任务/事件循环/核心下游）
const MonitorPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
  <div class="monitor-page">
    <!-- 顶部整体状态条 -->
    <div class="monitor-summary" :class="'monitor-s-' + (monitor ? monitor.status : 'loading')">
      <span class="monitor-summary-status">
        <span class="monitor-dot-lg" :class="'dot-' + (monitor ? monitor.status : 'loading')"></span>
        [[ statusText ]]
      </span>
      <span class="monitor-summary-count" v-if="monitor">
        正常 [[ monitor.summary.ok ]] ｜ 警告 [[ monitor.summary.warning ]] ｜ 异常 [[ monitor.summary.failed + monitor.summary.danger ]]
      </span>
      <span class="monitor-last-update" v-if="lastUpdate">最后更新 [[ lastUpdate ]]</span>
      <el-button size="small" style="margin-left:auto" @click="refreshNow">立即刷新</el-button>
    </div>

    <!-- 维度卡片网格：浅色卡片与整体背景一致，点击查看详情 -->
    <div class="monitor-grid" v-if="cards.length">
      <div v-for="card in cards" :key="card.key" class="monitor-card" :class="'monitor-card-' + card.status"
           title="点击查看详情" @click="openDetail(card)">
        <div class="monitor-card-head">
          <span class="monitor-dot" :class="'dot-' + card.status"></span>
          <span class="monitor-card-title">[[ card.title ]]</span>
          <span class="monitor-card-status">[[ statusLabel(card.status) ]]</span>
        </div>
        <div class="monitor-card-detail">[[ card.detail ]]</div>
        <div class="monitor-card-metrics">
          <div v-for="(v, k) in card.metrics" :key="k" class="monitor-metric">
            <el-tooltip v-if="metricTip(card.key, k)" :content="metricTip(card.key, k)" placement="top">
              <span class="metric-k metric-k-tip">[[ k ]]</span>
            </el-tooltip>
            <span v-else class="metric-k">[[ k ]]</span>
            <span class="metric-v" :class="{ 'metric-bad': String(v).indexOf('✗') >= 0 }">[[ v ]]</span>
          </div>
        </div>
      </div>
    </div>
    <el-empty v-else description="等待监控数据..." :image-size="80"></el-empty>

    <!-- 卡片详情弹窗：完整指标明细 -->
    <el-dialog v-model="detailVisible" :title="detailTitle" width="680px" :close-on-click-modal="true">
      <div v-if="detailCard" class="monitor-detail-body">
        <div class="monitor-detail-head">
          <span class="monitor-dot" :class="'dot-' + detailCard.status"></span>
          <b>[[ statusLabel(detailCard.status) ]]</b>
          <span>[[ detailCard.detail ]]</span>
        </div>
        <el-table :data="detailRows" size="small" border>
          <el-table-column prop="k" label="指标" width="220"></el-table-column>
          <el-table-column prop="v" label="当前值"></el-table-column>
        </el-table>
        <template v-if="detailRecent.length">
          <div class="monitor-detail-sub">最近请求耗时（最新 [[ detailRecent.length ]] 条）</div>
          <el-table :data="detailRecent" size="small" border max-height="280">
            <el-table-column prop="ts" label="时间" width="90"></el-table-column>
            <el-table-column label="接口">
              <template #default="scope"><span style="word-break:break-all">[[ scope.row.method ]] [[ scope.row.path ]]</span></template>
            </el-table-column>
            <el-table-column label="耗时" width="100">
              <template #default="scope"><span :class="{ 'metric-bad': scope.row.ms > 2000 }" style="font-family:Consolas,Menlo,monospace">[[ scope.row.ms ]]ms</span></template>
            </el-table-column>
          </el-table>
        </template>
        <div v-if="detailNote" class="monitor-detail-note">[[ detailNote ]]</div>
      </div>
    </el-dialog>
  </div>`,
  data() {
    return {
      monitor: null,
      lastUpdate: '',
      es: null,
      detailVisible: false,
      detailCard: null,
      detailRows: [],
      detailNote: '',
      detailRecent: [],
    };
  },
  computed: {
    detailTitle() {
      return this.detailCard ? this.detailCard.title + ' - 详情' : '详情';
    },
    statusText() {
      if (!this.monitor) return '连接中...';
      const map = { healthy: '运行健康', degraded: '状态降级', unhealthy: '运行异常' };
      return map[this.monitor.status] || this.monitor.status;
    },
    cards() {
      if (!this.monitor || !this.monitor.checks) return [];
      const defs = [
        { key: 'database', title: '数据库（连接池）', icon: 'db' },
        { key: 'redis', title: 'Redis 连接池', icon: 'redis' },
        { key: 'thread_pool', title: '线程池 / 协程池', icon: 'thread' },
        { key: 'task_queue', title: '异步任务队列', icon: 'queue' },
        { key: 'event_loop', title: '事件循环 / 请求延迟', icon: 'loop' },
        { key: 'downstream', title: '核心下游依赖', icon: 'link' },
      ];
      const self = this;
      return defs.map(function (d) {
        const c = self.monitor.checks[d.key] || { status: 'unknown', detail: '无数据', metrics: {} };
        const m = c.metrics || {};
        let metrics = {};
        if (d.key === 'database') {
          metrics = { '连接池': (m.checkedout != null ? m.checkedout : '-') + '/' + (m.total != null ? m.total : '-'), 'Ping': (m.ping_ms != null ? m.ping_ms : '-') + 'ms' };
        } else if (d.key === 'redis') {
          metrics = { '可用连接': m.available != null ? m.available : '-', '占用连接': m.in_use != null ? m.in_use : '-' };
        } else if (d.key === 'thread_pool') {
          metrics = { '活跃线程': m.active_threads != null ? m.active_threads : '-', '线程组成': (m.threads || []).length + ' 类', 'DB 连接': (m.checkedout != null ? m.checkedout : '-') + '/' + (m.total != null ? m.total : '-') };
        } else if (d.key === 'task_queue') {
          metrics = { '运行中': m.running != null ? m.running : '-', '最老任务': m.oldest_age_sec != null ? Math.round(m.oldest_age_sec / 60) + ' 分钟' : '-' };
        } else if (d.key === 'event_loop') {
          metrics = { 'P95': (m.p95_ms != null ? m.p95_ms : '-') + 'ms', 'P99': (m.p99_ms != null ? m.p99_ms : '-') + 'ms', '样本数': m.samples != null ? m.samples : '-' };
        } else if (d.key === 'downstream') {
          const items = m.items || {};
          metrics = {};
          const names = { mysql: 'MySQL', redis: 'Redis', auth_platform: 'authPlatform' };
          Object.keys(items).forEach(function (k) {
            const v = items[k];
            metrics[names[k] || k] = v.status === 'ok' ? '✓ 正常' : (v.status === 'skip' ? '跳过' : '✗ ' + (v.detail || '不可用'));
          });
        }
        return { key: d.key, title: d.title, status: c.status || 'unknown', detail: c.detail || '', metrics: metrics };
      });
    },
  },
  methods: {
    connect() {
      this.close();
      const token = localStorage.getItem('auth_token') || '';
      this.es = new EventSource('/api/monitor/stream?token=' + encodeURIComponent(token));
      this.es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.type === 'health') {
            this.monitor = d.data;
            this.lastUpdate = new Date().toLocaleTimeString('zh-CN', { hour12: false });
          }
        } catch (err) { /* 忽略解析错误 */ }
      };
      this.es.onerror = () => { /* EventSource 自动重连 */ };
    },
    refreshNow() {
      // 重建 SSE 立即获取一帧
      this.connect();
    },
    close() {
      if (this.es) { this.es.close(); this.es = null; }
    },
    statusLabel(s) {
      const map = { ok: '正常', warning: '警告', danger: '异常', failed: '异常', unknown: '未知' };
      return map[s] || s;
    },
    // 卡片指标悬浮解释（鼠标移上指标名查看口径）
    metricTip(cardKey, k) {
      const tips = {
        event_loop: {
          'P95': '95% 的请求耗时都低于该值，代表典型响应水平',
          'P99': '99% 的请求耗时都低于该值，用于捕捉偶发卡顿',
          '样本数': '最近参与统计的请求数（滑动窗口上限 200）',
        },
      };
      return (tips[cardKey] || {})[k] || '';
    },
    // 点击卡片查看详情：展开后端原始 metrics 为表格行
    openDetail(card) {
      this.detailCard = card;
      const raw = ((this.monitor || {}).checks || {})[card.key];
      const m = (raw && raw.metrics) || {};
      const rows = [];
      if (card.key === 'downstream') {
        const names = { mysql: 'MySQL', redis: 'Redis', auth_platform: 'authPlatform' };
        const items = m.items || {};
        Object.keys(items).forEach(function (k) {
          const it = items[k] || {};
          const label = names[k] || k;
          rows.push({ k: label + ' 状态', v: it.status === 'ok' ? '正常' : (it.status === 'skip' ? '跳过' : '异常') });
          if (it.ms != null) rows.push({ k: label + ' 探测耗时', v: it.ms + 'ms' });
          if (it.detail) rows.push({ k: label + ' 说明', v: it.detail });
        });
      } else {
        const labels = {
          ping_ms: 'Ping 耗时', checkedout: '已用连接', total: '连接池容量', size: '池大小',
          overflow: '当前溢出连接', available: '可用连接', in_use: '占用连接',
          active_threads: '活跃线程数', running: '运行中任务数', oldest_age_sec: '最老任务已运行',
          samples: '采样请求数', p95_ms: 'P95 耗时', p99_ms: 'P99 耗时',
          avg_ms: '平均耗时', min_ms: '最小耗时', max_ms: '最大耗时',
        };
        // 线程池维度：先展开线程组成明细（名称 ×数量 → 用途标注）
        if (card.key === 'thread_pool' && Array.isArray(m.threads)) {
          m.threads.forEach(function (t) {
            rows.push({ k: t.name + (t.count > 1 ? ' ×' + t.count : ''), v: t.usage });
          });
        }
        Object.keys(m).forEach(function (k) {
          if (m[k] == null || k === 'threads' || k === 'recent') return;
          let v = String(m[k]);
          if (k === 'oldest_age_sec') v = Math.round(m[k] / 60) + ' 分钟（' + m[k] + 's）';
          else if (k.indexOf('_ms') >= 0) v = m[k] + 'ms';
          rows.push({ k: labels[k] || k, v: v });
        });
      }
      this.detailRows = rows;
      this.detailRecent = (card.key === 'event_loop' && Array.isArray(m.recent)) ? m.recent : [];
      const notes = {
        database: '阈值：连接池占用 ≥90% 警告，池满异常',
        redis: 'Redis 未启用时显示为未启用',
        thread_pool: '阈值：活跃线程 ≥300 警告、≥600 异常；DB 连接池满异常',
        task_queue: '阈值：运行中任务 >3 或最老任务 >30 分钟警告',
        event_loop: 'P95 = 95% 的请求都快于该值（典型响应水平）；P99 = 99% 的请求都快于该值（捕捉偶发卡顿）。阈值：P99 >2s 警告、>5s 异常',
        downstream: '任一核心下游 failed 则整体异常',
      };
      this.detailNote = notes[card.key] || '';
      this.detailVisible = true;
    },
  },
  mounted() { this.connect(); },
  unmounted() { this.close(); },
};

// ── 样式 ──
(function () {
  const css = `
.monitor-page { padding: 4px 2px; }
.monitor-summary {
  display: flex; align-items: center; gap: 16px; padding: 12px 18px; border-radius: 8px;
  background: #fff; border: 1px solid #e4e7ed; margin-bottom: 14px;
}
.monitor-s-healthy { border-left: 4px solid #67c23a; }
.monitor-s-degraded { border-left: 4px solid #e6a23c; }
.monitor-s-unhealthy { border-left: 4px solid #f56c6c; }
.monitor-s-loading { border-left: 4px solid #909399; }
.monitor-summary-status { font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.monitor-summary-count { font-size: 13px; color: #606266; }
.monitor-last-update { font-size: 12px; color: #909399; }
.monitor-dot-lg { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.monitor-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.dot-ok, .dot-healthy { background: #67c23a; }
.dot-warning, .dot-degraded { background: #e6a23c; }
.dot-danger, .dot-failed, .dot-unhealthy { background: #f56c6c; }
.dot-loading, .dot-unknown { background: #909399; }
.monitor-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px;
}
.monitor-card {
  background: #fff; border-radius: 8px; padding: 14px 16px; border: 1px solid #e4e7ed;
  border-left: 4px solid #909399; cursor: pointer; transition: box-shadow .2s, transform .2s;
}
.monitor-card:hover { box-shadow: 0 4px 14px rgba(0, 0, 0, 0.08); transform: translateY(-1px); }
.monitor-card-ok { border-left-color: #67c23a; }
.monitor-card-warning { border-left-color: #e6a23c; }
.monitor-card-danger, .monitor-card-failed { border-left-color: #f56c6c; }
.monitor-card-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.monitor-card-title { color: #303133; font-size: 14px; font-weight: 600; }
.monitor-card-status { margin-left: auto; font-size: 12px; color: #909399; }
.monitor-card-ok .monitor-card-status { color: #67c23a; }
.monitor-card-warning .monitor-card-status { color: #e6a23c; }
.monitor-card-danger .monitor-card-status, .monitor-card-failed .monitor-card-status { color: #f56c6c; }
.monitor-card-detail { color: #606266; font-size: 12.5px; line-height: 1.6; margin-bottom: 10px; min-height: 20px; }
.monitor-card-metrics {
  display: flex; flex-wrap: wrap; gap: 6px 14px; border-top: 1px solid #ebeef5; padding-top: 10px;
}
.monitor-metric { font-size: 12px; color: #909399; display: flex; gap: 6px; align-items: baseline; }
.metric-k { color: #909399; }
.metric-k-tip { cursor: help; border-bottom: 1px dashed #c0c4cc; }
.metric-v { color: #303133; font-family: Consolas, Menlo, monospace; }
.metric-bad { color: #f56c6c; }
/* 详情弹窗 */
.monitor-detail-head {
  display: flex; align-items: center; gap: 8px; margin-bottom: 12px;
  padding: 10px 14px; background: #f5f7fa; border-radius: 6px; font-size: 13px; color: #606266;
}
.monitor-detail-note { margin-top: 10px; font-size: 12px; color: #909399; }
.monitor-detail-sub { margin: 12px 0 8px; font-size: 13px; font-weight: 600; color: #303133; }
`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);
})();
