// ============================================================
// 服务信息页 mixin：运行日志弹窗（SSE 实时流 + 分批渲染 + 全屏 + 暂停追踪）
//                  + 日志搜索（Ctrl+F；提交式：输入不渲染，点搜索/回车才渲染）
// ============================================================

const SvcMixinLog = {
  data() {
    return {
      // 日志弹窗
      logVisible: false,
      logFullscreen: false,  // 日志全屏模式（覆盖整个窗口，ESC 退出）
      logServiceName: '',
      logPods: [],
      logPod: '',
      logTail: 500,
      logLines: [],
      logSearchInput: '',  // 输入框实时值（不参与日志行渲染）
      logSearchWord: '',   // 已提交的搜索词（变化才触发行高亮渲染）
      logSearchMatches: [], logSearchIdx: -1,
      logStream: null,
      streamConnected: false,
      logPaused: false,  // 暂停追踪：断开 SSE 但保留已加载日志，供手动翻找
    };
  },
  created() {
    // 日志弹窗键盘事件（Ctrl+F 聚焦搜索 / ESC 退出全屏）；capture 捕获阶段注册，
    // 保证先于弹窗/下拉自身的 document 级 ESC 处理执行
    window.addEventListener('keydown', this.onLogKeydown, true);
  },
  beforeUnmount() {
    this.closeLogStream();
  },
  unmounted() {
    window.removeEventListener('keydown', this.onLogKeydown, true);
  },
  methods: {
    openLog(row, pod) {
      this.logServiceName = row.name;
      this.logPods = row.pods || [];
      this.logPod = pod ? pod.name : (this.logPods[0] ? this.logPods[0].name : '');
      this.logLines = [];
      svcLogKeySeq = 0;
      this.logVisible = true;
      if (this.logPod) this.connectLogStream();
    },
    // ─── 日志搜索（Ctrl+F；提交式：输入不渲染，点搜索/回车才渲染） ──
    updateLogSearch() {
      this.logSearchMatches = [];
      if (!this.logSearchWord) { this.logSearchIdx = -1; return; }
      const q = this.logSearchWord.toLowerCase();
      this.logLines.forEach((line, i) => { if (line.t.toLowerCase().includes(q)) this.logSearchMatches.push(line.k); });
      this.logSearchIdx = this.logSearchMatches.length ? 0 : -1;
      this._scrollToMatch();
    },
    // 聚焦搜索框即进入查询模式：自动暂停实时追踪，保留当前缓冲供检索
    onLogSearchFocus() {
      if (this.logStream) {
        this.closeLogStream();
        this.logPaused = true;
      }
    },
    // 提交搜索词：这一步才触发日志行高亮/匹配渲染（logSearchWord 变化 → SvcLogLines 重渲染）
    commitLogSearch() {
      if (this.logSearchWord !== this.logSearchInput) {
        this.logSearchWord = this.logSearchInput;
        this.updateLogSearch();
      } else {
        this._scrollToMatch();
      }
    },
    // 回车：输入有改动则提交搜索（跳首个匹配），无改动则跳下一个匹配
    onLogSearchEnter() {
      if (this.logSearchWord !== this.logSearchInput) this.commitLogSearch();
      else this.logSearchJump(1);
    },
    logSearchJump(dir) {
      if (!this.logSearchMatches.length) return;
      this.logSearchIdx = (this.logSearchIdx + dir + this.logSearchMatches.length) % this.logSearchMatches.length;
      this._scrollToMatch();
    },
    _scrollToMatch() {
      const idx = this.logSearchIdx;
      if (idx < 0 || !this.logSearchMatches.length) return;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (!box) return;
        const el = document.getElementById('logline-' + this.logSearchMatches[idx]);
        if (el) box.scrollTop = el.offsetTop - box.offsetTop - 8;
      });
    },
    onLogKeydown(e) {
      if (!this.logVisible) return;
      if (e.key === 'Escape') {
        // 弹窗内展开的下拉/弹层（如日志行数选择）的 ESC 先交由组件自身关闭，避免误退出全屏
        const t = e.target;
        if (t && t.closest && t.closest('.el-select, .el-select-dropdown, .el-popper')) return;
        // 全屏时 ESC 仅退出全屏（弹窗自身 ESC 关闭在全屏态已禁用）；非全屏由 el-dialog 原生关闭
        if (this.logFullscreen) {
          this.logFullscreen = false;
          e.preventDefault();
        }
        return;
      }
      if (e.ctrlKey && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
        if (this.$refs.logSearch) this.$refs.logSearch.focus();
      }
    },
    // 日志全屏切换（同一终端 DOM，流不断开，切换后滚动到底部）
    toggleLogFullscreen() {
      this.logFullscreen = !this.logFullscreen;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = box.scrollHeight;
      });
    },
    // 弹窗关闭（含 ESC 非全屏关闭）：重置全屏态并断开日志流
    onLogDialogClose() {
      this.logFullscreen = false;
      this.closeLogStream();
    },

    connectLogStream() {
      this.closeLogStream();
      this.logPaused = false;  // 重连即恢复实时追踪
      if (!this.logPod) return;
      this.logLines = [];
      svcLogKeySeq = 0;
      this._logPending = [];
      this._logRaf = null;
      // 实时（观察）模式不做搜索渲染：连接/重连时清空搜索状态
      this.logSearchInput = '';
      this.logSearchWord = '';
      this.logSearchMatches = [];
      this.logSearchIdx = -1;
      this.streamConnected = false;
      const token = localStorage.getItem('auth_token') || '';
      const params = new URLSearchParams({
        project: this.selectedProject,
        env: this.selectedEnv,
        pod: this.logPod,
        service: this.logServiceName || '',
        tail: String(this.logTail),
        token: token,
      });
      const es = new EventSource('/api/deploy/service-info/log/stream?' + params.toString());
      this.logStream = es;
      // 分批渲染：每帧最多刷 100 行，先出最新行，剩余渐进补全
      const self = this;
      function flushBatch() {
        self._logRaf = null;
        const pending = self._logPending;
        if (!pending.length) return;
        self._logPending = [];
        for (let i = 0; i < pending.length; i++) self.logLines.push(pending[i]);
        // 防内存膨胀：仅保留最近 1000 行
        if (self.logLines.length > 1000) self.logLines.splice(0, self.logLines.length - 1000);
        requestAnimationFrame(() => {
          const box = self.$refs.logBox;
          if (box) box.scrollTop = box.scrollHeight;
        });
      }
      function scheduleFlush() {
        if (!self._logRaf) self._logRaf = requestAnimationFrame(flushBatch);
      }
      es.onopen = () => { this.streamConnected = true; scheduleFlush(); };
      es.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data);
          if (d.error) {
            this._logPending.push({ k: ++svcLogKeySeq, t: '[错误] ' + d.error });
            flushBatch(); this.closeLogStream(); return;
          }
          if (d.end) {
            this._logPending.push({ k: ++svcLogKeySeq, t: '── 日志流结束（Pod 退出或重启）──' });
            flushBatch(); this.closeLogStream(); return;
          }
          this._logPending.push({ k: ++svcLogKeySeq, t: d.line });
          scheduleFlush();
        } catch (err) { /* 忽略非法帧 */ }
      };
      es.onerror = () => {
        // 日志流断连不自动重连（避免历史行重复刷屏），置为未连接由用户手动重连
        this.streamConnected = false;
        es.close();
        this.logStream = null;
      };
    },
    // 暂停/恢复追踪：暂停直接断开 SSE（不积压日志，保留已加载内容供手动翻找）；恢复则重新加载日志并继续 follow
    toggleLogPause() {
      if (this.logPaused) {
        this.connectLogStream();
      } else {
        this.closeLogStream();
        this.logPaused = true;
      }
    },
    closeLogStream() {
      if (this.logStream) {
        this.logStream.close();
        this.logStream = null;
      }
      this.streamConnected = false;
    },
    // 清屏：仅清空前端缓冲日志，不影响后端/SSE 流（新日志继续追加）
    clearLogScreen() {
      this.logLines = [];
      this._logPending = [];
      if (this._logRaf) { cancelAnimationFrame(this._logRaf); this._logRaf = null; }
      this.logSearchInput = '';
      this.logSearchWord = '';
      this.logSearchMatches = [];
      this.logSearchIdx = -1;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = 0;
      });
    },
  },
};
