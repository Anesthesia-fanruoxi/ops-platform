// ============================================================
// 服务信息页 mixin：构建进度抽屉（步骤条 + 实时日志 SSE + 取消/重跑）
//                  + 环境进行中构建状态订阅（工具栏运行状态指示器）
// ============================================================

const SvcMixinBuildProgress = {
  data() {
    return {
      // 构建进度抽屉
      bpDrawerVisible: false,
      bpBuild: null,
      bpSteps: [],
      bpLogFull: '',  // 全量日志缓冲（仅 all 模式 SSE 累积）
      bpLogByStep: {},  // 步骤归属日志缓冲（后端帧带 step，前端纯渲染）
      bpLogMode: 'all',
      bpStepES: null,
      bpES: null,
      bpNow: Date.now(),
      bpTimer: null,
      selectedEnvData: {},  // 当前环境详情（含最近构建记录 builds）
      activeBuild: null,   // 当前环境进行中的构建（SSE 推送，点击打开进度抽屉）
      envBuildStream: null,
      // 构建记录弹窗
      buildRecordsVisible: false,
      buildRecords: [],
      buildRecordsLoading: false,
    };
  },
  computed: {
    // 部署步骤 waiting：后端未配置服务目录，需勾选回填后重新构建
    bpDeployWaiting() {
      return (this.bpSteps || []).some(s => s.key === 'deploy' && (
        s.status === 'waiting' || s.action === 'configure_artifact_dirs'
      ));
    },
    // 当前环境最近构建记录（backend/frontend 两行，按时间倒序）
    envBuilds() {
      const builds = (this.selectedEnvData || {}).builds || {};
      const rows = [];
      if (builds.backend) rows.push({ ...builds.backend, project_type: 'backend' });
      if (builds.frontend) rows.push({ ...builds.frontend, project_type: 'frontend' });
      return rows.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
    },
    buildStatusText() {
      return (st) => ({ pending: '等待中', running: '构建中', success: '成功', failed: '失败', cancelled: '已取消' }[st] || st || '-');
    },
    // 最近一次构建（backend/frontend 取时间最新一条）——工具栏靠右展示执行人/分支/时间
    lastBuild() {
      return this.envBuilds[0] || null;
    },
  },
  beforeUnmount() {
    this.closeEnvBuildStream();
  },
  methods: {
    // ═══════════ 构建记录弹窗 ═══════════
    openBuildRecordsDialog() {
      this.buildRecordsVisible = true;
      this.loadBuildRecords();
    },
    loadBuildRecords() {
      const env = this.selectedEnvData;
      if (!env || !env.id) return;
      this.buildRecordsLoading = true;
      ajax('GET', '/api/cicd/builds?environment_id=' + env.id, null, (r) => {
        this.buildRecordsLoading = false;
        if (r.code === 200) this.buildRecords = r.data || [];
      }, () => { this.buildRecordsLoading = false; });
    },
    onBuildRecordClick(row) {
      this.buildRecordsVisible = false;
      this.openProgressDrawer({ id: row.id, build_no: row.build_no, status: row.status, project_type: row.project_type, branch: row.branch });
    },
    // ═══════════ 构建进度抽屉（与环境信息页一致） ═══════════
    openProgressDrawer(build) {
      this.bpBuild = build;
      this.bpSteps = [];
      this.bpLogFull = '';
      this.bpLogByStep = {};
      this.bpLogMode = 'all';
      this.bpDrawerVisible = true;
      this.stopBpTimer();
      this.bpNow = Date.now();
      this.bpTimer = setInterval(() => { this.bpNow = Date.now(); }, 100);
      this.connectBuildSteps();
    },
    connectBuildSteps() {
      this.disconnectBpSteps();
      const token = localStorage.getItem('auth_token') || '';
      const url = '/api/cicd/builds/' + this.bpBuild.id + '/steps/stream?token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.bpStepES = es;
      es.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        this.bpSteps = data.steps || [];
        if (!this.bpES) {
          this.connectBuildLog('all');
        }
        const buildStatus = data.build_status;
        if (buildStatus) {
          const prevStatus = this.bpBuild.status;
          this.bpBuild = Object.assign({}, this.bpBuild, { status: buildStatus });
          // 构建终态但部署步骤可能仍在执行（Master 自动部署），不能立即断开；
          // 等后端发 done 帧（构建终态 + 部署步骤终态）再断开步骤流
          if (data.done) {
            this.disconnectBpSteps();
          }
          if (['success', 'failed', 'cancelled'].includes(buildStatus)) {
            if (prevStatus === 'running' || prevStatus === 'pending') {
              this.loadEnvs();
            }
          }
        }
      };
      es.onerror = () => {
        es.close();
        this.bpStepES = null;
        this.fetchBuildSteps();
      };
    },
    disconnectBpSteps() {
      if (this.bpStepES) { this.bpStepES.close(); this.bpStepES = null; }
    },
    fetchBuildSteps() {
      if (!this.bpBuild) return;
      ajax('GET', '/api/cicd/builds/' + this.bpBuild.id + '/steps', null, (res) => {
        if (res.code === 200 && res.data) {
          this.bpSteps = res.data.steps || [];
          if (res.data.build_status) {
            this.bpBuild = Object.assign({}, this.bpBuild, { status: res.data.build_status });
          }
        }
      });
    },
    connectBuildLog(type) {
      // 始终只维持 1 条 all 模式 SSE；切换步骤只改本地视图，不重连
      this.disconnectBpLog();
      const token = localStorage.getItem('auth_token') || '';
      const url = '/api/cicd/builds/' + this.bpBuild.id + '/log?type=all&follow=true&token=' + encodeURIComponent(token);
      const es = new EventSource(url);
      this.bpES = es;
      es.onmessage = (evt) => {
        let obj;
        try { obj = JSON.parse(evt.data); } catch (e) { return; }
        const text = obj.text || '';
        if (!text) return;
        this.bpLogFull += text;
        if (obj.step) {
          this.bpLogByStep[obj.step] = (this.bpLogByStep[obj.step] || '') + text;
        }
        this.$nextTick(() => {
          const c = this.$refs.bpLogContainer;
          if (c) c.scrollTop = c.scrollHeight;
        });
      };
      es.onerror = () => { es.close(); this.bpES = null; };
    },
    disconnectBpLog() {
      if (this.bpES) { this.bpES.close(); this.bpES = null; }
    },
    bpStepType(stepNo) {
      return { 1: 'git', 2: 'mvn', 3: 'product', 4: 'build', 5: 'push', 6: 'deploy' }[stepNo] || 'git';
    },
    bpStatusType(status) {
      const map = { success: 'success', failed: 'danger', running: 'warning', pending: 'info', cancelled: 'info' };
      return (typeof status === 'string' && map[status]) || 'info';
    },
    bpStatusText(status) {
      const map = { success: '成功', failed: '失败', running: '运行中', pending: '等待中', cancelled: '已取消' };
      if (typeof status === 'string' && map[status]) return map[status];
      return (typeof status === 'string' && status) || '';
    },
    bpStepStatus(step) {
      if (!step) return 'wait';
      if (step.status === 'success') return 'success';
      if (step.status === 'running' || step.status === 'waiting') return 'process';
      if (step.status === 'failed') return 'error';
      return 'wait';
    },
    parseStepTime(str) {
      const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?/.exec(str || '');
      if (!m) return NaN;
      const ms = m[7] ? m[7].padEnd(3, '0') : '0';
      return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6], +ms).getTime();
    },
    fmtDuration(sec) {
      sec = Math.max(0, sec);
      const s = Math.floor(sec);
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const ss = (s % 60).toString().padStart(2, '0');
      const dec = Math.round((sec - s) * 10);
      if (h > 0) return h + ':' + m.toString().padStart(2, '0') + ':' + ss;
      if (m > 0) return m + ':' + ss;
      return s + '.' + dec + 's';
    },
    bpStepDuration(s) {
      if (s.status === 'running' && s.started_at) {
        const st = this.parseStepTime(s.started_at);
        if (!isNaN(st)) return this.fmtDuration((this.bpNow - st) / 1000);
      }
      if (s.duration) return this.fmtDuration(s.duration);
      return '';
    },
    // 当前视图日志（后端已按步骤归属拆分，前端仅取缓冲 + 渲染限量 500KB）
    bpLogView() {
      let text = this.bpLogMode === 'all' ? this.bpLogFull : (this.bpLogByStep[this.bpLogMode] || '');
      if (!text) return '';
      const MAX = 512000;  // 500KB
      if (text.length > MAX) {
        return '...（日志过长，仅显示尾部 ' + Math.round(MAX / 1024) + 'KB）...\n' + text.slice(-MAX);
      }
      return text;
    },
    switchBpLog(stepNo) {
      // 切换步骤只改本地视图，不重连 SSE
      this.bpLogMode = this.bpStepType(stepNo);
    },
    switchBpLogAll() {
      this.bpLogMode = 'all';
    },
    stopBpPolling() {
      this.disconnectBpSteps();
      this.disconnectBpLog();
    },
    stopBpTimer() {
      if (this.bpTimer) { clearInterval(this.bpTimer); this.bpTimer = null; }
    },
    closeProgressDrawer() {
      this.bpDrawerVisible = false;
      this.stopBpPolling();
      this.stopBpTimer();
    },
    cancelBuild() {
      if (!this.bpBuild) return;
      ajax('POST', '/api/cicd/builds/' + this.bpBuild.id + '/cancel', null, (res) => {
        if (res.code === 200) ElementPlus.ElMessage.success('已请求取消');
        else ElementPlus.ElMessage.error(res.msg || '取消失败');
      });
    },
    rerunFromStep(stepNo) {
      if (!this.bpBuild) return;
      const step = this.bpSteps.find(s => s.step_no === stepNo);
      const stepName = step ? step.name : ('步骤' + stepNo);
      ElementPlus.ElMessageBox.confirm(
        '将从「' + stepName + '」开始重新执行至最后一步，复用已完成步骤的代码与产物（不重新克隆）。确定继续？',
        '从指定步骤重跑',
        { confirmButtonText: '确定重跑', cancelButtonText: '取消', type: 'warning' }
      ).then(() => {
        ajax('POST', '/api/cicd/builds/' + this.bpBuild.id + '/rerun', { start_step: stepNo }, (res) => {
          if (res.code === 200) {
            ElementPlus.ElMessage.success(res.msg || '已加入重跑队列');
            this.bpBuild = Object.assign({}, this.bpBuild, res.data || {}, { error_msg: '' });
            this.bpLogFull = '';
            this.connectBuildSteps();
            this.connectBuildLog('all');
          } else {
            ElementPlus.ElMessage.error(res.msg || '重跑失败');
          }
        });
      }).catch(() => { /* 取消确认 */ });
    },
    // 订阅环境进行中构建状态（SSE，5s 一帧；构建可能来自环境信息页）。
    // 每次订阅前先断开上一个 SSE；切换环境/项目后，旧连接残留帧按 environment_id 丢弃，
    // 避免误把上个环境的构建状态显示在当前环境上。
    subscribeEnvBuilds() {
      this.closeEnvBuildStream();
      this.activeBuild = null;
      const env = this.selectedEnvData;
      if (!env || !env.id) return;
      const envId = env.id;
      const token = localStorage.getItem('auth_token') || '';
      const es = new EventSource('/api/cicd/builds/env/' + envId + '/stream?token=' + encodeURIComponent(token));
      this.envBuildStream = es;
      es.onmessage = (evt) => {
        try {
          const d = JSON.parse(evt.data);
          // 流已断开或环境已切换：丢弃不属于当前环境的推送
          if (d.environment_id !== envId || !this.envBuildStream || this.selectedEnvData.id !== envId) return;
          const builds = d.builds || [];
          const run = builds.find(b => b.status === 'running') || builds.find(b => b.status === 'pending') || null;
          const wasRunning = !!this.activeBuild;
          this.activeBuild = run ? { id: run.id, build_no: run.build_no, status: run.status, project_type: run.project_type, branch: run.branch, current_step: run.current_step || '' } : null;
          // 进行中构建结束：刷新普通 list 接口，让「最近构建」状态及时更新
          if (wasRunning && !run) this.loadEnvs();
        } catch (e) { /* 忽略解析错误 */ }
      };
      es.onerror = () => {
        es.close();
        this.envBuildStream = null;
        // 流断开时清掉残留的「构建中」指示，避免 SSE 断开后 UI 卡死在构建态
        if (this.activeBuild) {
          this.activeBuild = null;
          this.loadEnvs();
        }
        // 自动重连：10s 后重建 SSE（仅当环境未切换、未主动关闭）
        setTimeout(() => {
          if (this.selectedEnvData && this.selectedEnvData.id === envId && !this.envBuildStream) {
            this.subscribeEnvBuilds();
          }
        }, 10000);
      };
    },
    closeEnvBuildStream() {
      if (this.envBuildStream) { this.envBuildStream.close(); this.envBuildStream = null; }
    },
  },
};
