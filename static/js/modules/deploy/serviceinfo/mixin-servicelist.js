// ============================================================
// 服务信息页 mixin：环境收藏 / 上次选择回填 / 项目环境加载 /
//                  服务列表（卡片 SSE + HTTP 回退）/ 服务重启 / 卡片渲染
// ============================================================

const SvcMixinServiceList = {
  data() {
    return {
      projects: [],
      projectList: [],  // [{id, name}] 保留 id 供快捷部署触发
      selectedProject: '',
      envs: [],
      envList: [],  // [{id, environment}] 保留 id 供快捷部署触发
      selectedEnv: '',
      favorites: [],          // 当前用户的环境收藏（来自后端，按 user_id 隔离）
      favCollapsed: false,    // 收藏栏是否收起
      favDrag: null,          // 拖拽中的源：{type:'group', project} 或 {type:'item', id}
      services: [],
      loading: false,
      k8sError: '',
      envHasNacos: true,     // 环境是否部署 Nacos（middleware 判定，snapshot 帧携带；false 时隐藏全部 Nacos 入口）
      svcStream: null,       // 服务卡片 SSE 流（EventSource）
      svcStreamRetry: null,  // SSE 断连重连定时器

      restarting: {},         // 各服务「重启」按钮 loading 态（按 svc.name 记录，避免互相影响）
      restartingAll: false,   // 「重启全部服务」按钮 loading 态
    };
  },
  computed: {
    canDeploy() {
      return this.$auth.hasPermission('op:cicd_build');
    },
    // 收藏按项目自动父归纳（纯展示层分组，数据仍为扁平 sort_no）：
    // 组顺序 = 各组内最小 sort_no；组内按 sort_no 升序
    favGroups() {
      const sorted = this.favorites.slice().sort((a, b) => (a.sort_no || 0) - (b.sort_no || 0));
      const map = new Map();
      sorted.forEach((f) => {
        if (!map.has(f.project_name)) map.set(f.project_name, []);
        map.get(f.project_name).push(f);
      });
      return Array.from(map.entries()).map(([project, items]) => ({ project, items }));
    },
  },
  mounted() {
    this.loadFavorites();
    this.restoreLastSelection();
  },
  created() {
    this.loadProjects();
  },
  beforeUnmount() {
    this.closeSvcStream();
  },
  methods: {
    // ─── 环境收藏（按用户落库） ──────────────────────────────
    loadFavorites() {
      ajax('GET', '/api/deploy/service-info/favorites', null, (r) => {
        if (r.code === 200) this.favorites = r.data || [];
      });
    },
    // ─── 上次选择回填（localStorage 持久化，刷新后自动恢复） ──
    persistSelection() {
      if (!this.selectedProject || !this.selectedEnv) return;
      try {
        localStorage.setItem('svc_last_selection', JSON.stringify({
          project: this.selectedProject,
          env: this.selectedEnv,
        }));
      } catch (e) { /* 忽略存储异常 */ }
    },
    restoreLastSelection() {
      let saved = null;
      try {
        saved = JSON.parse(localStorage.getItem('svc_last_selection') || 'null');
      } catch (e) { saved = null; }
      if (!saved || !saved.project) return;
      this.selectedProject = saved.project;
      // 环境列表需异步加载（与 onProjectChange 相同逻辑，但不能直接调它——它会清空 selectedEnv）
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(saved.project), null, (r) => {
        this.envList = ((r.data || {}).list || []);
        this.envs = this.envList.map(e => e.environment);
        this.syncSelectedEnvData();
        if (saved.env && this.envs.includes(saved.env)) {
          this.selectedEnv = saved.env;
          this.loadServices();
        } else if (saved.env) {
          // 环境已被删除：保留项目，仅提示重新选择环境
          ElementPlus.ElMessage.warning('上次选择的环境已不存在，请重新选择');
        }
      });
    },
    addFavorite() {
      if (!this.selectedProject || !this.selectedEnv) {
        ElementPlus.ElMessage.warning('请先选择项目与环境');
        return;
      }
      const proj = this.projectList.find(p => p.name === this.selectedProject);
      const env = this.envList.find(e => e.environment === this.selectedEnv) || this.selectedEnvData;
      if (!proj || !env || !env.id) {
        ElementPlus.ElMessage.warning('无法识别当前项目/环境');
        return;
      }
      if (this.favorites.some(f => f.project_name === this.selectedProject && f.env_name === this.selectedEnv)) {
        ElementPlus.ElMessage.info('已收藏');
        return;
      }
      ajax('POST', '/api/deploy/service-info/favorites', { project_id: proj.id, env_id: env.id }, (r) => {
        if (r.code === 200) {
          if (!this.favorites.some(f => f.id === r.data.id)) this.favorites.unshift(r.data);
          ElementPlus.ElMessage.success('已收藏');
        } else {
          ElementPlus.ElMessage.warning(r.msg || '收藏失败');
        }
      });
    },
    removeFavorite(id) {
      ajax('DELETE', '/api/deploy/service-info/favorites/' + id, null, (r) => {
        if (r.code === 200) {
          this.favorites = this.favorites.filter(f => f.id !== id);
        } else {
          ElementPlus.ElMessage.warning(r.msg || '取消收藏失败');
        }
      });
    },
    // ─── 收藏拖拽排序（原生 HTML5 DnD，落库持久化；组整组拖拽 + 组内/跨组子项拖拽） ─────────
    _sortedFavs() {
      return this.favorites.slice().sort((a, b) => (a.sort_no || 0) - (b.sort_no || 0));
    },
    // 乐观更新本地顺序并持久化（sort_no 重编号为 0..n）
    persistFavOrder(list) {
      this.favorites = list.map((f, i) => Object.assign({}, f, { sort_no: i }));
      ajax('PUT', '/api/deploy/service-info/favorites/sort',
        { order: list.map(f => f.id) }, (r) => {
          if (r.code !== 200) ElementPlus.ElMessage.warning(r.msg || '排序保存失败');
        });
    },
    // 子项（环境卡）拖拽
    onFavDragStart(fav, e) {
      this.favDrag = { type: 'item', id: fav.id };
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(fav.id));   // Firefox 必需
    },
    // drop 到某张环境卡：移动到该卡位置（可跨组，分组是纯展示计算）
    onFavDrop(fav) {
      const drag = this.favDrag;
      this.favDrag = null;
      if (!drag || drag.type !== 'item' || drag.id === fav.id) return;
      const list = this._sortedFavs();
      const fromIdx = list.findIndex(f => f.id === drag.id);
      const toIdx = list.findIndex(f => f.id === fav.id);
      if (fromIdx < 0 || toIdx < 0) return;
      const [moved] = list.splice(fromIdx, 1);
      list.splice(toIdx, 0, moved);
      this.persistFavOrder(list);
    },
    // 组头拖拽（整组移动）
    onFavGroupDragStart(group, e) {
      this.favDrag = { type: 'group', project: group.project };
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', 'g:' + group.project);
    },
    // drop 到某组头：整组移动到该组位置（组内相对顺序不变）
    onFavGroupDrop(targetGroup) {
      const drag = this.favDrag;
      this.favDrag = null;
      if (!drag || drag.type !== 'group' || drag.project === targetGroup.project) return;
      const groups = this.favGroups.slice();
      const fromIdx = groups.findIndex(g => g.project === drag.project);
      const toIdx = groups.findIndex(g => g.project === targetGroup.project);
      if (fromIdx < 0 || toIdx < 0) return;
      const [moved] = groups.splice(fromIdx, 1);
      groups.splice(toIdx, 0, moved);
      this.persistFavOrder(groups.flatMap(g => g.items));
    },
    // drop 到组空白区：把拖拽中的环境卡追加到该组末尾
    onFavGroupItemDrop(group) {
      const drag = this.favDrag;
      this.favDrag = null;
      if (!drag || drag.type !== 'item') return;
      const list = this._sortedFavs();
      const fromIdx = list.findIndex(f => f.id === drag.id);
      if (fromIdx < 0) return;
      const [moved] = list.splice(fromIdx, 1);
      const tail = group.items.length ? group.items[group.items.length - 1] : null;
      const insertAt = tail ? list.findIndex(f => f.id === tail.id) + 1 : list.length;
      list.splice(insertAt, 0, moved);
      this.persistFavOrder(list);
    },
    selectFavorite(item) {
      // 跨项目：重置并加载目标项目环境列表后回填；同项目：仅换环境
      if (this.selectedProject !== item.project_name) {
        this.closeEnvBuildStream();
        this.closeSvcStream();
        this.activeBuild = null;
        this.selectedEnv = '';
        this.services = [];
        this.envs = [];
        this.selectedProject = item.project_name;
      }
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(item.project_name), null, (r) => {
        this.envList = ((r.data || {}).list || []);
        this.envs = this.envList.map(e => e.environment);
        this.syncSelectedEnvData();
        if (this.envs.includes(item.env_name)) {
          this.selectedEnv = item.env_name;
          this.loadServices();
        } else {
          ElementPlus.ElMessage.warning('该环境已不存在，请重新选择');
        }
      });
    },
    toggleFavBar() {
      this.favCollapsed = !this.favCollapsed;
    },
    loadProjects() {
      ajax('GET', '/api/admin/projects', null, (r) => {
        this.projectList = r.data || [];
        this.projects = this.projectList.map(p => p.name);
      });
    },
    onProjectChange() {
      // 切换项目：立即断开上一个环境的构建状态 SSE 与服务卡片 SSE，再重置选择
      this.closeEnvBuildStream();
      this.closeSvcStream();
      this.activeBuild = null;
      this.selectedEnv = '';
      this.services = [];
      this.envs = [];
      if (!this.selectedProject) return;
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(this.selectedProject), null, (r) => {
        this.envList = ((r.data || {}).list || []);
        this.envs = this.envList.map(e => e.environment);
        this.syncSelectedEnvData();
      });
    },
    // 拉取环境列表并记录当前环境的构建记录（builds：backend/frontend 最近构建）
    loadEnvs() {
      if (!this.selectedProject) return;
      ajax('GET', '/api/manage/environments/list?project=' + encodeURIComponent(this.selectedProject), null, (r) => {
        if (r.code === 200) {
          this.envList = ((r.data || {}).list || []);
          this.envs = this.envList.map(e => e.environment);
          this.syncSelectedEnvData();
        }
      });
    },
    syncSelectedEnvData() {
      const cur = this.envList.find(e => e.environment === this.selectedEnv);
      this.selectedEnvData = cur || {};
      this.subscribeEnvBuilds();
    },
    loadServices() {
      // 主数据源：SSE 实时流（快照 + 增量，滚动更新实时可见）；断连/出错自动回退 HTTP
      if (!this.selectedProject || !this.selectedEnv) return;
      this.persistSelection();  // 记录"上次选择"，供页面刷新后回填
      this.syncSelectedEnvData();
      this.closeSvcStream();
      this.k8sError = '';
      this.loading = true;
      this.connectSvcStream();
    },
    // 服务卡片 SSE 订阅：snapshot/update 全量替换 services；error/多次断连回退 HTTP
    connectSvcStream() {
      const token = localStorage.getItem('auth_token') || '';
      const params = new URLSearchParams({
        project: this.selectedProject,
        env: this.selectedEnv,
        token: token,
      });
      const es = new EventSource('/api/deploy/service-info/stream?' + params.toString());
      this.svcStream = es;
      let failCount = 0;
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.type === 'snapshot' || d.type === 'update') {
            this.services = d.services || [];
            if (d.type === 'snapshot') this.envHasNacos = d.env_has_nacos !== false;   // 仅快照帧携带
            this.k8sError = '';
            this.loading = false;
          } else if (d.type === 'error') {
            this.k8sError = d.error || 'SSE 不可用';
            this.closeSvcStream();
            this.loadServicesHttp();
          }
          // heartbeat 忽略（保活）
        } catch (err) { /* 忽略非法帧 */ }
      };
      es.onerror = () => {
        // 网络断连：EventSource 默认自动重连；连续失败则回退 HTTP
        failCount++;
        if (failCount >= 3) {
          this.closeSvcStream();
          this.loading = false;
          this.k8sError = 'SSE 连接失败，已回退 HTTP';
          this.loadServicesHttp();
        }
      };
    },
    closeSvcStream() {
      if (this.svcStream) {
        this.svcStream.close();
        this.svcStream = null;
      }
    },
    // HTTP 列表回退（SSE 不可用 / 后端 K8s 不可用）
    loadServicesHttp() {
      const url = '/api/deploy/service-info/list?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv);
      ajax('GET', url, null, (r) => {
        const d = r.data || {};
        this.services = d.list || [];
        this.envHasNacos = d.env_has_nacos !== false;
        if (d.k8s_error) this.k8sError = d.k8s_error;
        this.loading = false;
      });
    },

    // 单服务重启：二次确认 → loading → rollout restart → 刷新卡片（观察 pod 滚动重建）
    restartService(svc) {
      ElementPlus.ElMessageBox.confirm(
        '确定重启服务「' + svc.name + '」吗？其内部 Pod 会滚动重建，期间可能短暂不可用。',
        '重启服务', { type: 'warning', confirmButtonText: '确定重启', cancelButtonText: '取消' }
      ).then(() => {
        this.restarting[svc.name] = true;
        ajax('POST', '/api/deploy/service-info/restart',
          { project: this.selectedProject, env: this.selectedEnv, service_name: svc.name }, (r) => {
            if (r.code === 200) {
              ElementPlus.ElMessage.success('已触发 ' + svc.name + ' 重启');
            } else {
              ElementPlus.ElMessage.error(r.msg || '重启失败');
            }
            delete this.restarting[svc.name];
            this.loadServices();  // 重建 SSE 快照，体现 Pod 重建过程
          });
      }).catch(() => { /* 取消确认：不触发任何请求 */ });
    },

    // 重启全部服务：强确认 → loading → 整 namespace 逐个 rollout restart → 刷新
    restartAllServices() {
      ElementPlus.ElMessageBox.confirm(
        '将对该命名空间下所有服务（所有 Pod）执行滚动重启，全部服务会短暂不可用，确定继续？',
        '重启全部服务', { type: 'warning', confirmButtonText: '确定重启全部', cancelButtonText: '取消' }
      ).then(() => {
        this.restartingAll = true;
        ajax('POST', '/api/deploy/service-info/restart-all',
          { project: this.selectedProject, env: this.selectedEnv }, (r) => {
            if (r.code === 200) {
              const d = r.data || {};
              if (d.failed && d.failed.length) {
                ElementPlus.ElMessage.warning(
                  '重启完成：' + (d.succeeded ? d.succeeded.length : 0) + ' 个成功 / '
                  + d.failed.length + ' 个失败（' + d.failed.map(x => x.name).join('、') + '）');
              } else {
                ElementPlus.ElMessage.success('已触发全部服务重启（共 ' + (d.total || 0) + ' 个）');
              }
            } else {
              ElementPlus.ElMessage.error(r.msg || '重启全部服务失败');
            }
            this.restartingAll = false;
            this.loadServices();  // 刷新，观察全 namespace pod 滚动重建
          });
      }).catch(() => { /* 取消确认：不触发任何请求 */ });
    },
    // 镜像标题：多镜像（滚动更新期间）时展示全部
    svcImageTitle(svc) {
      const imgs = (svc.images && svc.images.length) ? svc.images : (svc.image ? [svc.image] : []);
      return imgs.join('\n');
    },

    // 运行时间：基于最新版本控制器的创建时间（后端 version_created_at，UTC ISO）计算已运行时长
    svcFormatUptime(createdAt) {
      if (!createdAt) return '-';
      let ts;
      try { ts = new Date(createdAt).getTime(); } catch (e) { return '-'; }
      if (!ts || isNaN(ts)) return '-';
      const diff = Date.now() - ts;
      if (diff < 0) return '-';
      const MIN = 60e3, HOUR = 3600e3, DAY = 86400e3;
      if (diff < MIN) return '刚刚';
      if (diff < HOUR) return Math.floor(diff / MIN) + ' 分钟';
      if (diff < DAY) return Math.floor(diff / HOUR) + ' 小时 ' + Math.floor((diff % HOUR) / MIN) + ' 分钟';
      return Math.floor(diff / DAY) + ' 天 ' + Math.floor((diff % DAY) / HOUR) + ' 小时';
    },

    podTagType(pod) {
      if (pod.reason) return 'danger';
      if (pod.phase === 'Running') return 'success';
      if (pod.phase === 'Pending') return 'warning';
      return 'info';
    },
    // 状态标签文案：phase 中文 + 异常原因
    podStatusText(pod) {
      const map = { Running: '运行中', Pending: '等待中', Succeeded: '已完成', Failed: '失败', Unknown: '未知' };
      const base = map[pod.phase] || pod.phase || 'Unknown';
      return pod.reason ? base + '·' + pod.reason : base;
    },
    svcCardDotClass(svc) {
      if (!svc.pods || !svc.pods.length) return 'off';
      if (svc.pods.some(p => p.reason)) return 'err';
      if (svc.pods.some(p => p.phase !== 'Running')) return 'warn';
      return 'ok';
    },
    svcCardDotTitle(svc) {
      if (!svc.pods || !svc.pods.length) return '未部署（无 Pod）';
      const running = svc.pods.filter(p => p.phase === 'Running' && !p.reason).length;
      return running + '/' + svc.pods.length + ' 个 Pod 运行中';
    },
  },
};
