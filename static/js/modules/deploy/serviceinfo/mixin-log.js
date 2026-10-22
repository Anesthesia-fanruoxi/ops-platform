// ============================================================
// 服务信息页 mixin：运行日志弹窗（SSE 实时流 + 分批渲染 + 全屏）
//                  + 搜索（Ctrl+F；提交式：回车/清空才触发高亮，实时流也照常渲染高亮）
//                  + 暂停追踪（连接保持，新行进积压区不渲染；积压满 500 行断开，需重连）
//                  + 恢复追踪（积压按约 20 行 / 0.5 秒平滑吐出）
// ============================================================

const SvcMixinLog = {
  data() {
    return {
      // 日志弹窗
      logVisible: false,
      logFullscreen: false,  // 日志全屏模式（覆盖整个窗口，ESC 先退出全屏，再按才关闭）
      logServiceName: '',
      logPods: [],
      logPod: '',
      logTail: 500,
      logLines: [],          // 已渲染的日志行 [{ k, t }]
      logSearchInput: '',    // 输入框实时值（不参与日志行渲染）
      logSearchWord: '',     // 已提交的搜索词（回车/清空才变化）
      logSearchIdx: -1,
      logUnsub: null,        // 日志 SSE 退订函数（SseHub 多路复用）
      streamConnected: false,
      logPaused: false,      // 手动暂停渲染：SSE 保持连接，新行只进积压区
      logReading: false,     // 上滚阅读（不在底部）：同样只积压不渲染
      logDetached: false,    // 积压满额后已主动断开，需用户点「重连」
      logBacklogCount: 0,    // 积压行数（响应式，供状态显示）
    };
  },
  computed: {
    // 是否处于「追踪中但不实时渲染」：手动暂停 / 搜索中 / 上滚阅读
    logBuffering() {
      return this.logPaused || !!this.logSearchWord || this.logReading;
    },
    // 匹配行 key 列表（随 logLines 增量增长自动跟随，实时追踪时也照常高亮）
    logSearchMatches() {
      const q = (this.logSearchWord || '').toLowerCase();
      if (!q) return [];
      const out = [];
      this.logLines.forEach(l => { if (l.t.toLowerCase().includes(q)) out.push(l.k); });
      return out;
    },
    // 当前定位到的匹配行 key（用于行内「深黄」+ 整行青色强调）
    logCurrentKey() {
      if (this.logSearchIdx < 0) return null;
      const k = this.logSearchMatches[this.logSearchIdx];
      return k === undefined ? null : k;
    },
    logStatusColor() {
      if (this.logDetached || !this.streamConnected) return '#f56c6c';
      if (this.logBuffering || this.logBacklogCount) return '#e6a23c';
      return '#67c23a';
    },
    logStatusText() {
      const n = this.logBacklogCount;
      const q = n ? '（积压 ' + n + ' 行）' : '';
      if (!this.streamConnected) {
        return this.logDetached ? '已断开' + q + '，请重连' : '未连接';
      }
      if (this.logPaused) return '已暂停追踪' + q;
      if (this.logSearchWord) return '搜索中·暂停渲染' + q;
      if (this.logReading) return '阅读中·暂停渲染' + q;
      if (n) return '正在追平积压（剩 ' + n + ' 行）';
      return '实时跟随中';
    },
  },
  watch: {
    // 从不渲染切回实时渲染时按节奏吐积压；反向则停止吐字（保留积压）
    logBuffering(v) {
      if (v) this.stopDrain();
      else if (this._logBacklog && this._logBacklog.length) this.startDrain();
    },
  },
  created() {
    // 日志弹窗键盘事件（Ctrl+F 聚焦搜索 / ESC 全屏缩小或关闭）；capture 捕获阶段注册，
    // 保证先于弹窗/下拉自身的 document 级 ESC 处理执行
    window.addEventListener('keydown', this.onLogKeydown, true);
  },
  beforeUnmount() {
    this.stopDrain();
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
      this.logSearchInput = '';
      this.logSearchWord = '';
      this.logSearchIdx = -1;
      this.logReading = false;
      this.logPaused = false;
      this.resetLogBuffer();
      this.logVisible = true;
      if (this.logPod) this.connectLogStream();
    },
    // 在独立浏览器标签页打开运行日志（/log-view 独立整页视图，实时追踪同弹窗）
    openLogInNewTab() {
      const params = new URLSearchParams({
        type: 'live',
        project: this.selectedProject,
        env: this.selectedEnv,
        service: this.logServiceName || '',
        pod: this.logPod || '',
        tail: String(this.logTail),
      });
      // 独立轻量页 /log-view（不走 SPA，首屏只加载日志所需资源）
      window.open('/log-view?' + params.toString(), '_blank');
    },
    // ─── 日志搜索（Ctrl+F 聚焦；回车提交并跳首个，之后回车/↑/↓ 循环跳转） ──
    commitLogSearch() {
      this.logSearchWord = this.logSearchInput;
      this.$nextTick(() => {
        this.logSearchIdx = this.logSearchMatches.length ? 0 : -1;
        if (this.logSearchIdx >= 0) this._scrollToMatch();
      });
    },
    onLogSearchEnter() {
      if (this.logSearchWord !== this.logSearchInput) this.commitLogSearch();
      else this.logSearchJump(1);
    },
    logSearchJump(dir) {
      const n = this.logSearchMatches.length;
      if (!n) return;
      this.logSearchIdx = (this.logSearchIdx + dir + n) % n;
      this._scrollToMatch();
    },
    _scrollToMatch() {
      const idx = this.logSearchIdx;
      if (idx < 0 || !this.logSearchMatches.length) return;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (!box) return;
        const el = document.getElementById('logline-' + this.logSearchMatches[idx]);
        if (!el) return;
        // 用包围盒差值定位，避免 offsetParent 不在同一个滚动容器里导致跳动
        const br = box.getBoundingClientRect();
        const er = el.getBoundingClientRect();
        box.scrollTop += (er.top - br.top) - 40;
      });
    },
    onLogKeydown(e) {
      if (!this.logVisible) return;
      if (e.key === 'Escape') {
        // 弹窗内展开的下拉/弹层（如日志行数选择）的 ESC 先交由组件自身关闭，避免误退出全屏
        const t = e.target;
        if (t && t.closest && t.closest('.el-select, .el-select-dropdown, .el-popper')) return;
        // ESC 两级语义：全屏 → 先退出全屏；非全屏 → 再关闭弹窗。
        // 弹窗自身的 closeOnPressEscape 已固定为 false，ESC 全部由这里统一处理，
        // 并用 stopPropagation 拦住焦点陷阱（ElFocusTrap）的 release-requested，
        // 否则退出全屏的同一按键会继续冒泡把弹窗一起关掉。
        e.preventDefault();
        e.stopPropagation();
        if (this.logFullscreen) {
          this.logFullscreen = false;
        } else {
          this.logVisible = false;
          this.closeLogStream();
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
    // 弹窗关闭（含 ESC 非全屏关闭）：重置全屏态/暂停态并断开日志流
    onLogDialogClose() {
      this.logFullscreen = false;
      this.logPaused = false;
      this.logReading = false;
      this.resetLogBuffer();
      this.closeLogStream();
    },

    // ─── 日志流 ──────────────────────────────────────────────
    connectLogStream() {
      this.closeLogStream();
      this.resetLogBuffer();
      this.logPaused = false;
      this.logReading = false;
      if (!this.logPod) return;
      // 重连 = 重建：清空已渲染行，重新拉取最近 tail 行（搜索词保留，重建后继续高亮）
      this.logLines = [];
      svcLogKeySeq = 0;
      this._logPending = [];
      this._logRaf = null;
      this.streamConnected = false;
      // 走 SseHub 多路复用：与首页监控/服务列表/构建状态共用同一条浏览器连接
      const self = this;
      const topic = 'log:' + this.selectedProject + ':' + this.selectedEnv + ':'
        + this.logPod + ':' + (this.logServiceName || '') + ':' + String(this.logTail);
      this.logUnsub = SseHub.subscribe(topic, {
        onopen: () => {
          // 连接（重）建 = 重建：清空已渲染行，服务器会重放最近 tail 行
          self.streamConnected = true;
          self.logLines = [];
          svcLogKeySeq = 0;
          self._logPending = [];
          self._logRaf = null;
          self._scheduleLogFlush();
        },
        onmessage: (d) => {
          if (d.error) {
            self.onStreamEnd('[错误] ' + d.error);
            return;
          }
          if (d.end) {
            self.onStreamEnd('── 日志流结束（Pod 退出或重启）──');
            return;
          }
          if (d.line !== undefined) self.receiveLogLine(d.line);
        },
        onerror: () => {
          // 断连：置为未连接（EventSource/SseHub 会按原 URL 自动重连）
          self.streamConnected = false;
        },
      });
    },
    // 流结束/出错：提示行排在积压尾部（有积压时继续按节奏吐），随后断开
    onStreamEnd(text) {
      this.logPaused = false;
      this.logReading = false;
      this.logDetached = false;
      const line = { k: ++svcLogKeySeq, t: text };
      if (this._logBacklog && this._logBacklog.length) {
        this._logBacklog.push(line);
        this.logBacklogCount = this._logBacklog.length;
        this.startDrain();
      } else {
        this._logPending.push(line);
        this.flushLogBatch();
      }
      this.closeLogStream();
    },
    // 收到一行：不渲染状态（暂停 / 搜索中 / 上滚阅读）→ 只进积压区；
    // 追平积压中 → 排到积压尾部保序；真正跟随时才分批渲染
    receiveLogLine(text) {
      if (this.logDetached) return;  // 已断开的残留帧直接丢弃
      if (!this._logBacklog) this._logBacklog = [];
      const line = { k: ++svcLogKeySeq, t: text };
      if (this.logBuffering) {
        this._logBacklog.push(line);
        this.logBacklogCount = this._logBacklog.length;
        if (this.logBacklogCount >= SVC_LOG_BACKLOG_MAX && !this.logDetached) {
          // 积压满额：停止追踪，等用户重连（重连会重建并重新拉取内容）
          this.closeLogStream();
          this.logDetached = true;
        }
        return;
      }
      if (this._logBacklog.length) {
        // 还在吐积压：新行排队保序，避免插队导致日志顺序错乱
        this._logBacklog.push(line);
        if (this._logBacklog.length > SVC_LOG_BACKLOG_HARD_MAX) {
          this._logBacklog.splice(0, this._logBacklog.length - SVC_LOG_BACKLOG_HARD_MAX);
        }
        this.logBacklogCount = this._logBacklog.length;
        return;
      }
      this._logPending.push(line);
      this._scheduleLogFlush();
    },
    _scheduleLogFlush() {
      if (this._logRaf) return;
      this._logRaf = requestAnimationFrame(() => this.flushLogBatch());
    },
    flushLogBatch() {
      if (this._logRaf) {
        cancelAnimationFrame(this._logRaf);
        this._logRaf = null;
      }
      const pending = this._logPending;
      if (!pending || !pending.length) return;
      this._logPending = [];
      this.appendLogLines(pending);
      // 不渲染状态下保持当前视口（搜索定位 / 上滚阅读都不拽回底部）
      if (!this.logBuffering) this._scrollLogBottom();
    },
    appendLogLines(list) {
      for (let i = 0; i < list.length; i++) this.logLines.push(list[i]);
      // 防内存膨胀：仅保留最近 SVC_LOG_MAX_LINES 行
      if (this.logLines.length > SVC_LOG_MAX_LINES) {
        this.logLines.splice(0, this.logLines.length - SVC_LOG_MAX_LINES);
      }
    },
    _scrollLogBottom() {
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = box.scrollHeight;
      });
    },
    // 终端滚动：离开底部即进入「阅读模式」（只积压不渲染）
    onLogBoxScroll() {
      const box = this.$refs.logBox;
      if (!box) return;
      this.logReading = box.scrollTop + box.clientHeight < box.scrollHeight - 40;
    },
    // 手动暂停/恢复渲染：SSE 连接始终保留，恢复后按节奏吐积压
    toggleLogPause() {
      this.logPaused = !this.logPaused;
      // 恢复时若停在历史位置，回到最新（搜索定位中保持原位）
      if (!this.logPaused && !this.logSearchWord && this.logReading) {
        this.logReading = false;
        this._scrollLogBottom();
      }
    },
    // 点击积压：回到底部 + 立即吐完积压 + 恢复实时渲染（会清空搜索）
    logJumpToLive() {
      this.logPaused = false;
      this.logReading = false;
      this.logSearchInput = '';
      this.logSearchWord = '';
      this.logSearchIdx = -1;
      this.stopDrain();
      if (this._logBacklog && this._logBacklog.length) {
        this.appendLogLines(this._logBacklog.splice(0, this._logBacklog.length));
        this.logBacklogCount = 0;
      }
      this._scrollLogBottom();
    },
    startDrain() {
      if (this._drainTimer || this.logBuffering) return;
      this._drainTimer = setInterval(() => this.drainStep(), SVC_LOG_DRAIN_MS);
    },
    drainStep() {
      if (!this._logBacklog || !this._logBacklog.length) { this.stopDrain(); return; }
      if (this.logBuffering) { this.stopDrain(); return; }
      const batch = this._logBacklog.splice(0, SVC_LOG_DRAIN_BATCH);
      this.logBacklogCount = this._logBacklog.length;
      this.appendLogLines(batch);
      this._scrollLogBottom();
      if (!this._logBacklog.length) this.stopDrain();
    },
    stopDrain() {
      if (this._drainTimer) {
        clearInterval(this._drainTimer);
        this._drainTimer = null;
      }
    },
    resetLogBuffer() {
      this.stopDrain();
      this._logBacklog = [];
      this._logPending = [];
      this.logBacklogCount = 0;
      this.logDetached = false;
    },
    closeLogStream() {
      if (this.logUnsub) {
        this.logUnsub();
        this.logUnsub = null;
      }
      if (this._logRaf) {
        cancelAnimationFrame(this._logRaf);
        this._logRaf = null;
      }
      this._logPending = [];
      this.streamConnected = false;
    },
    // 清屏：仅清空前端已渲染内容与积压缓冲，不影响后端/SSE 流（新日志继续追加）
    clearLogScreen() {
      this.logLines = [];
      this.resetLogBuffer();
      this.logReading = false;
      this.logSearchInput = '';
      this.logSearchWord = '';
      this.logSearchIdx = -1;
      this.$nextTick(() => {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = 0;
      });
    },
  },
};
