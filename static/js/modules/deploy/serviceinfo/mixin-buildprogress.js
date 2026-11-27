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
      bpLogFrames: [],     // 总览日志按帧追加渲染（只重画新帧，不重算全量字符串）
      bpLogFrameSeq: 0,
      bpLogFrameChars: 0,
      bpLogByStep: {},  // 步骤归属日志缓冲（后端帧带 step，前端纯渲染）
      bpLogMode: 'all',
      bpStepES: null,
      bpES: null,
      bpNow: Date.now(),
      bpTimer: null,
      selectedEnvData: {},  // 当前环境详情（含最近构建记录 builds）
      activeBuild: null,   // 当前环境进行中的构建（SSE 推送，点击打开进度抽屉）
      envBuildUnsub: null,   // 环境构建状态 SSE 退订函数（SseHub 多路复用）
      // 构建记录弹窗（多仓项目展示批次列表，单仓项目展示构建列表）
      buildRecordsVisible: false,
      buildRecords: [],
      batchRecords: [],
      recordsMode: 'builds',
      buildRecordsLoading: false,
      // 多仓批次进度抽屉（一次发版按服务展示各自构建进度）
      batchDrawerVisible: false,
      batchData: null,
      batchLoading: false,
      batchTimer: null,
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
    // 摘要底色随构建结果：成功绿/失败红，其他状态保持默认灰
    lastBuildBgClass() {
      const s = (this.lastBuild || {}).status;
      if (s === 'success') return 'svc-lb-success';
      if (s === 'failed') return 'svc-lb-failed';
      return '';
    },
  },
  beforeUnmount() {
    this.closeEnvBuildStream();
    this.stopBatchTimer();
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
      const loadLegacy = () => {
        this.recordsMode = 'builds';
        ajax('GET', '/api/cicd/builds?environment_id=' + env.id, null, (r) => {
          this.buildRecordsLoading = false;
          if (r.code === 200) this.buildRecords = r.data || [];
        });
      };
      if (!env.project_id) { loadLegacy(); return; }
      // 多仓项目：这里按批次展示，点批次看该批次每个服务的进度
      ajax('GET', '/api/cicd/multi-templates/by-project/' + env.project_id, null, (r) => {
        if (r.code !== 200 || !r.data || !(r.data.items || []).length) { loadLegacy(); return; }
        this.recordsMode = 'batches';
        ajax('GET', '/api/cicd/multi-templates/batches?environment_id=' + env.id, null, (br) => {
          this.buildRecordsLoading = false;
          if (br.code === 200) this.batchRecords = br.data || [];
          else loadLegacy();
        });
      });
    },
    onBuildRecordClick(row) {
      this.buildRecordsVisible = false;
      this.openProgressDrawer({ id: row.id, build_no: row.build_no, status: row.status, project_type: row.project_type, branch: row.branch });
    },
    onBatchRecordClick(row) {
      this.buildRecordsVisible = false;
      this.openBatchDrawer(row.id);
    },
    // 顶部「构建中」与「最近构建」：属于多仓批次的直接打开批次进度
    openActiveBuild() {
      if (!this.activeBuild) return;
      if (this.activeBuild.batch_id) this.openBatchDrawer(this.activeBuild.batch_id);
      else this.openProgressDrawer(this.activeBuild);
    },
    openLastBuild() {
      const b = this.lastBuild;
      if (!b) return;
      if (b.batch_id) this.openBatchDrawer(b.batch_id);
      else this.openProgressDrawer({ id: b.id, build_no: b.build_no, status: b.status, project_type: b.project_type, branch: b.branch });
    },
    // ═══════════ 多仓批次进度抽屉 ═══════════
    // 多仓一次发版 = 一个批次，抽屉内按服务逐行展示各自构建状态；
    // 点击服务行打开该构建的步骤/日志抽屉，不再跳转独立页面。
    openBatchDrawer(batchId) {
      if (!batchId) return;
      this.batchDrawerVisible = true;
      this.batchData = null;
      this.loadBatchDetail(batchId);
      this.stopBatchTimer();
      this.batchTimer = setInterval(() => this.loadBatchDetail(batchId), 3000);
    },
    loadBatchDetail(batchId) {
      if (!this.batchDrawerVisible) return;
      this.batchLoading = this.batchData === null;
      ajax('GET', '/api/cicd/multi-templates/batches/' + batchId, null, (r) => {
        this.batchLoading = false;
        if (r.code !== 200 || !r.data) return;
        this.batchData = r.data;
        // 批次终态：停止轮询并刷新环境最近构建摘要
        if (['success', 'failed', 'cancelled'].includes(r.data.status)) {
          this.stopBatchTimer();
          this.loadEnvs();
        }
      }, () => { this.batchLoading = false; });
    },
    stopBatchTimer() {
      if (this.batchTimer) { clearInterval(this.batchTimer); this.batchTimer = null; }
    },
    closeBatchDrawer() {
      this.batchDrawerVisible = false;
      this.batchData = null;
      this.stopBatchTimer();
    },
    openBatchRepo(row) {
      if (!row || !row.build_id) return;
      this.openProgressDrawer({
        id: row.build_id, build_no: row.build_no, status: row.status,
        project_type: row.project_type || 'backend', branch: row.branch,
      });
    },
    // ═══════════ 构建进度抽屉（与环境信息页一致） ═══════════
    openProgressDrawer(build) {
      this.bpBuild = build;
      this.bpSteps = [];
      this.resetBpLog();
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
        this.pushLogFrame(text);
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
    bpStepType(stepNo, stepKey) {
      // 通知步骤沿用部署日志面板；前端发布日志归入 build
      if (stepKey === 'notify') return 'deploy';
      if (stepKey === 'publish') return 'build';
      return { 1: 'git', 2: 'mvn', 3: 'product', 4: 'build', 5: 'push', 6: 'deploy', 7: 'deploy' }[stepNo] || 'git';
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
    // 总览日志按帧追加：只新增 DOM 节点，不重算全量字符串；超过 500KB 丢弃最旧帧
    pushLogFrame(text) {
      const MAX = 512000;
      this.bpLogFrames.push({ id: ++this.bpLogFrameSeq, text });
      this.bpLogFrameChars += text.length;
      while (this.bpLogFrameChars > MAX && this.bpLogFrames.length > 1) {
        const drop = this.bpLogFrames.shift();
        this.bpLogFrameChars -= drop.text.length;
      }
    },
    resetBpLog() {
      this.bpLogFrames = [];
      this.bpLogFrameSeq = 0;
      this.bpLogFrameChars = 0;
      this.bpLogByStep = {};
    },
    // 分步骤视图日志（总览走帧渲染，不再拼大字符串）
    bpLogView() {
      let text = this.bpLogByStep[this.bpLogMode] || '';
      if (!text) return '';
      const MAX = 512000;  // 500KB
      if (text.length > MAX) {
        return '...（日志过长，仅显示尾部 ' + Math.round(MAX / 1024) + 'KB）...\n' + text.slice(-MAX);
      }
      return text;
    },
    switchBpLog(stepNo, stepKey) {
      // 切换步骤只改本地视图，不重连 SSE
      this.bpLogMode = this.bpStepType(stepNo, stepKey);
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
            this.resetBpLog();
            this.connectBuildSteps();
            this.connectBuildLog('all');
          } else {
            ElementPlus.ElMessage.error(res.msg || '重跑失败');
          }
        });
      }).catch(() => { /* 取消确认 */ });
    },
    // 订阅环境进行中构建状态（SSE，5s 一帧；构建可能来自环境信息页）。
    // 走 SseHub 多路复用：与首页监控/服务列表共用同一条连接。
    // 每次订阅前先退订上一个；切换环境/项目后，旧连接残留帧按 environment_id 丢弃，
    // 避免误把上个环境的构建状态显示在当前环境上。
    subscribeEnvBuilds() {
      this.closeEnvBuildStream();
      this.activeBuild = null;
      const env = this.selectedEnvData;
      if (!env || !env.id) return;
      const envId = env.id;
      this.envBuildUnsub = SseHub.subscribe('builds_env:' + envId, {
        onmessage: (d) => {
          try {
            // 流已断开或环境已切换：丢弃不属于当前环境的推送
            if (d.environment_id !== envId || !this.envBuildUnsub || this.selectedEnvData.id !== envId) return;
            const builds = d.builds || [];
            const run = builds.find(b => b.status === 'running') || builds.find(b => b.status === 'pending') || null;
            const wasRunning = !!this.activeBuild;
            this.activeBuild = run ? { id: run.id, build_no: run.build_no, status: run.status, project_type: run.project_type, branch: run.branch, batch_id: run.batch_id, current_step: run.current_step || '' } : null;
            // 进行中构建结束：刷新普通 list 接口，让「最近构建」状态及时更新
            if (wasRunning && !run) this.loadEnvs();
          } catch (e) { /* 忽略解析错误 */ }
        },
        onerror: () => {
          // 流断开时清掉残留的「构建中」指示，避免 SSE 断开后 UI 卡死在构建态
          if (this.activeBuild) {
            this.activeBuild = null;
            this.loadEnvs();
          }
        },
      });
    },
    closeEnvBuildStream() {
      if (this.envBuildUnsub) { this.envBuildUnsub(); this.envBuildUnsub = null; }
    },
  },
};
