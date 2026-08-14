// 首页组件：登录后默认落地页（无权限/超管/普通用户均展示）
// 内容：欢迎横幅 + 平台健康监控（SSE，迁移自监控信息页）+ 平台概况统计 + 最近构建 + 快捷入口
const DashboardPage = {
  name: 'DashboardPage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
  <div class="dashboard-page">
    <div class="dash-hero">
      <div class="dash-hello">你好，[[ nickname ]] 👋</div>
      <div class="dash-sub">[[ roleName || '未分配角色' ]] · 欢迎使用运维平台</div>
      <div class="dash-hero-meta">[[ now ]] · [[ location ]]</div>
    </div>

    <!-- 平台健康监控（SSE 实时） -->
    <div class="dash-section-title">平台健康监控</div>
    <div class="dash-monitor">
      <div class="dash-monitor-summary" :class="'dash-ms-' + (monitor ? monitor.status : 'loading')">
        <span class="dash-dot-lg" :class="'dot-' + (monitor ? monitor.status : 'loading')"></span>
        <span class="dash-monitor-status-text">[[ monitorStatusText ]]</span>
        <span v-if="monitor" class="dash-monitor-count">正常 [[ monitor.summary.ok ]] ｜ 警告 [[ monitor.summary.warning ]] ｜ 异常 [[ monitor.summary.failed + monitor.summary.danger ]]</span>
        <span v-if="lastUpdate" class="dash-monitor-time">最后更新 [[ lastUpdate ]]</span>
      </div>
      <div class="dash-monitor-grid" v-if="monitorCards.length">
        <div v-for="card in monitorCards" :key="card.key" class="dash-monitor-card" :class="'dash-mc-' + card.status">
          <div class="dash-monitor-card-head">
            <span class="dash-dot" :class="'dot-' + card.status"></span>
            <span class="dash-monitor-card-title">[[ card.title ]]</span>
            <span class="dash-monitor-card-status">[[ statusLabel(card.status) ]]</span>
          </div>
          <div class="dash-monitor-card-detail">[[ card.detail ]]</div>
          <div class="dash-monitor-card-metrics">
            <div v-for="(v, k) in card.metrics" :key="k" class="dash-monitor-metric">
              <span class="dash-monitor-metric-k">[[ k ]]</span>
              <span class="dash-monitor-metric-v">[[ v ]]</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="dash-two-col">
      <div>
        <div class="dash-section-title" v-if="recentBuilds.length">最近构建</div>
        <div v-if="recentBuilds.length" class="dash-builds">
          <div v-for="b in recentBuilds" :key="b.build_no" class="dash-build">
            <span class="dash-build-no">[[ b.build_no ]]</span>
            <span class="dash-build-pname">[[ b.project_name || '-' ]]</span>
            <span class="dash-build-env">[[ b.environment_name || '-' ]]</span>
            <span class="dash-build-branch">[[ b.branch ]]</span>
            <span class="dash-build-type">[[ b.project_type === 'frontend' ? '前端' : '后端' ]]</span>
            <span class="dash-build-status" :class="'bs-' + b.status">[[ statusText(b.status) ]]</span>
            <span class="dash-build-time">[[ b.created_at ]]</span>
          </div>
        </div>
        <div class="dash-section-title" v-else-if="!loadingStats">暂无构建记录</div>
      </div>
      <div>
        <div class="dash-section-title" v-if="entryGroups.length">快捷入口</div>
        <div class="dash-entry-groups" v-if="entryGroups.length">
          <div v-for="g in entryGroups" :key="g.label" class="dash-entry-group">
            <div class="dash-entry-group-title">
              <span class="dash-entry-group-icon">[[ g.icon ]]</span>
              <span>[[ g.label ]]</span>
            </div>
            <div class="dash-entry-group-items">
              <div v-for="m in g.children" :key="m.path" class="dash-entry-group-item"
                   @click="go(m.path)">
                <span class="dash-entry-item-text">[[ m.label ]]</span>
                <span class="dash-entry-item-arrow">›</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
  `,
  data() {
    return {
      now: '', location: window.location.host || '', entryGroups: [],
      loadingStats: false, stats: {}, recentBuilds: [],
      monitor: null, monitorChecks: {}, lastUpdate: '', _monitorTimer: null,
    };
  },
  computed: {
    username() { return authState.username || ''; },
    nickname() { return authState.nickname || authState.username || '访客'; },
    roleName() { return authState.roleName || ''; },
    monitorStatusText() {
      if (!this.monitor) return '检测中…';
      const map = { healthy: '运行健康', degraded: '状态降级', unhealthy: '运行异常' };
      return map[this.monitor.status] || this.monitor.status;
    },
    monitorCards() {
      if (!Object.keys(this.monitorChecks).length) return [];
      const defs = [
        { key: 'database', title: '数据库（连接池）' },
        { key: 'redis', title: 'Redis 连接池' },
        { key: 'thread_pool', title: '线程池 / 协程池' },
        { key: 'task_queue', title: '异步任务队列' },
        { key: 'event_loop', title: '事件循环 / 请求延迟' },
        { key: 'downstream', title: '核心下游依赖' },
      ];
      const self = this;
      return defs.map(function (d) {
        const c = self.monitorChecks[d.key] || { status: 'unknown', detail: '加载中…', metrics: {} };
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
  mounted() {
    this.now = this.formatNow();
    setInterval(() => { this.now = this.formatNow(); }, 1000);
    this.buildEntryGroups();
    setTimeout(() => this.buildEntryGroups(), 300); // 菜单异步加载兜底：稍后重建入口卡
    this.fetchStats();
    this.startMonitor();
  },
  beforeUnmount() {
    this.closeMonitor();
    this._timer && clearInterval(this._timer);
  },
  watch: {
    '$root.menuItems': { deep: true, handler() { this.buildEntryGroups(); } },
  },
  methods: {
    formatNow() {
      const d = new Date();
      const p = (n) => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    },
    go(path) { this.$router.push(path); },
    fetchStats() {
      this.loadingStats = true;
      ajax('GET', '/api/dashboard/stats', null, (res) => {
        this.loadingStats = false;
        if (res.code === 200 && res.data) {
          this.stats = res.data;
          this.recentBuilds = res.data.recent_builds || [];
        }
      }, () => { this.loadingStats = false; });
    },
    statusText(st) {
      return { pending: '等待中', running: '构建中', success: '成功', failed: '失败', cancelled: '已取消' }[st] || st;
    },
    statusLabel(s) {
      const map = { ok: '正常', warning: '警告', danger: '异常', failed: '异常', unknown: '未知' };
      return map[s] || s;
    },
    // 监控卡数据走接口轮询：整体健康 + 六维度单卡（/api/dashboard/monitor/xxx）
    startMonitor() {
      this.closeMonitor();
      this.fetchMonitor();
      this._monitorTimer = setInterval(() => this.fetchMonitor(), 5000);
    },
    fetchMonitor() {
      const ajaxP = (url) => new Promise((resolve) => {
        ajax('GET', url, null, (res) => resolve(res && res.code === 200 ? res.data : null), () => resolve(null));
      });
      ajaxP('/api/dashboard/monitor/health').then((d) => {
        if (d) { this.monitor = d; this.lastUpdate = new Date().toLocaleTimeString('zh-CN', { hour12: false }); }
      });
      const keys = ['database', 'redis', 'thread_pool', 'task_queue', 'event_loop', 'downstream'];
      Promise.all(keys.map((k) => ajaxP('/api/dashboard/monitor/' + k))).then((list) => {
        const obj = {};
        keys.forEach((k, i) => { if (list[i]) obj[k] = list[i]; });
        this.monitorChecks = obj;
      });
    },
    closeMonitor() {
      if (this._monitorTimer) { clearInterval(this._monitorTimer); this._monitorTimer = null; }
    },
    // 快捷入口：按父菜单分组（每组展示子菜单），按权限过滤，取前 5 组
    buildEntryGroups() {
      const menus = (this.$root && this.$root.menuItems) || [];
      const groups = [];
      (menus || []).forEach(g => {
        const children = (g.children || []).filter(m =>
          m.path && m.label && m.permission && authState.hasPermission && authState.hasPermission(m.permission));
        if (children.length) {
          groups.push({ label: g.label || g.key, icon: g.icon || '', children });
        }
      });
      this.entryGroups = groups.slice(0, 5);
    },
  },
};
