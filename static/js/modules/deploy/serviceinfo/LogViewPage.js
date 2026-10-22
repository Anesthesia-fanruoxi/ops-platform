// ============================================================
// 服务日志独立标签页查看（/log-view）
//   type=live：SSE 实时追踪（等价运行日志弹窗）
//   type=file：NFS 日志文件内容（等价日志内容弹窗）
// 路由 meta.standalone = true → base.html 不渲染侧边栏/顶栏，整页只放日志
// 依赖：svc-shared.js（svcHighlightLine / SvcLogLines）、svc-styles.js（终端样式）
// ============================================================

const SvcLogViewPage = {
  name: 'SvcLogViewPage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  components: { SvcLogLines },
  data() {
    return {
      lvType: 'live',
      lvProject: '',
      lvEnv: '',
      lvService: '',
      lvPod: '',
      lvFile: '',
      lvTail: 500,
      // 统一行结构 { k: 稳定 key, t: 文本 }，file/live 共用 SvcLogLines 渲染
      lines: [],
      seq: 0,
      loading: false,
      loadingTip: '',
      searchInput: '',
      searchWord: '',
      searchIdx: -1,
      // live 模式状态
      streamUnsub: null,   // 日志 SSE 退订函数（SseHub 多路复用）
      connecting: false,    // 正在建立连接（避免按钮/状态闪烁）
      connected: false,
      paused: false,        // 暂停追踪：SSE 保持连接，新行只进积压区
      detached: false,      // 积压满额后已主动断开，需点「重连」
      backlogCount: 0,      // 积压行数（响应式，供状态显示）
      // 自动跟随到底部（用户向上滚动查看历史时暂停，回到底部后恢复）
      followTail: true,
    };
  },
  computed: {
    lvTitle() {
      if (this.lvType === 'file') return '日志内容 - ' + (this.lvFile || '');
      let t = '运行日志 - ' + (this.lvService || '');
      if (this.lvPod) t += ' / ' + this.lvPod;
      return t;
    },
    lvSubTitle() {
      if (this.lvType === 'file') return this.lvService || '';
      return this.lvService || '';
    },
    // 匹配行 key 列表（流式增量填充时自动跟随）
    lvMatches() {
      const q = (this.searchWord || '').toLowerCase();
      if (!q) return [];
      const out = [];
      this.lines.forEach(l => { if (l.t.toLowerCase().includes(q)) out.push(l.k); });
      return out;
    },
    // 当前定位到的匹配行 key（行内深黄 + 整行青色强调）
    lvCurrentKey() {
      if (this.searchIdx < 0) return null;
      const k = this.lvMatches[this.searchIdx];
      return k === undefined ? null : k;
    },
    // 是否处于「追踪中但不实时渲染」：手动暂停 / 正在搜索 / 上滚阅读
    // 此时新日志只进积压区，不打断 SSE 连接
    buffering() {
      return this.paused || !!this.searchWord || !this.followTail;
    },
    streamStateText() {
      const n = this.backlogCount;
      const q = n ? '（积压 ' + n + ' 行）' : '';
      if (this.connecting) return '连接中…';
      if (!this.connected) {
        return this.detached ? '已断开' + q + '，请重连' : '未连接';
      }
      if (this.paused) return '已暂停追踪' + q;
      if (this.searchWord) return '搜索中·暂停渲染' + q;
      if (!this.followTail) return '阅读中·暂停渲染' + q;
      if (n) return '正在追平积压（剩 ' + n + ' 行）';
      return '实时跟随中';
    },
    streamDotColor() {
      if (this.connecting) return '#e6a23c';
      if (!this.connected) return '#f56c6c';
      if (this.paused || this.searchWord || !this.followTail || this.backlogCount) return '#e6a23c';
      return '#67c23a';
    },
    // 「回到底部」只在手动上滚时出现；搜索定位期间不弹（搜索时不会自动跟随）
    showBackToBottom() {
      return !this.followTail && !this.searchWord;
    },
  },
  watch: {
    // 从「不渲染」切回「实时渲染」时，把积压按节奏吐出；反之停止吐字（保留积压）
    buffering(v) {
      if (v) this.stopDrain();
      else if (this._backlog && this._backlog.length) this.startDrain();
    },
    // 诊断用：首行日志到达耗时（区分「页面慢」还是「日志流慢」）
    'lines.length'(n) {
      if (n && !this._firstLineAt) {
        this._firstLineAt = performance.now();
        console.info('[log-view] 首行日志 ' + Math.round(this._firstLineAt) + 'ms');
      }
    },
  },
  created() {
    // 参数全部来自路由 query（新标签页 URL：#/log-view?type=live&project=..&env=..&service=..）
    const q = this.$route.query || {};
    this.lvType = q.type === 'file' ? 'file' : 'live';
    this.lvProject = q.project || '';
    this.lvEnv = q.env || '';
    this.lvService = q.service || '';
    this.lvPod = q.pod || '';
    this.lvFile = q.file || '';
    this.lvTail = Number(q.tail) || 500;
    // 文件流加载代次：清屏 / 重新加载时自增，用于作废仍在读取中的旧流
    this._loadGen = 0;
  },
  mounted() {
    document.title = this.lvTitle + ' - 运维平台';
    window.addEventListener('keydown', this.onKeydown);
    if (this.lvType === 'file') this.loadFile();
    else this.connectStream();
  },
  beforeUnmount() {
    window.removeEventListener('keydown', this.onKeydown);
    this.stopDrain();
    this.closeStream();
  },
  methods: {
    // ─── 通用：滚动 ──────────────────────────────────────────
    scrollToBottom(force) {
      const box = this.$refs.box;
      if (!box) return;
      box.scrollTop = box.scrollHeight;
      if (force) this.followTail = true;
    },
    onBoxScroll() {
      const box = this.$refs.box;
      if (!box) return;
      // 实时维护「是否在底部」：上滚即进入阅读模式（新行进积压、不渲染）
      this.followTail = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    },
    // ─── 搜索定位（Ctrl+F 聚焦；回车提交并跳首个，之后回车/↑/↓ 循环） ──
    onKeydown(e) {
      if (e.ctrlKey && (e.key === 'f' || e.key === 'F')) {
        e.preventDefault();
        if (this.$refs.searchInput) this.$refs.searchInput.focus();
      }
    },
    // 清空输入框（含 @clear）：同步清掉已提交搜索词，取消高亮
    commitSearch() {
      this.searchWord = this.searchInput;
      if (!this.searchWord) this.searchIdx = -1;
    },
    onSearchEnter() {
      if (this.searchWord !== this.searchInput) {
        this.searchWord = this.searchInput;
        this.$nextTick(() => {
          this.searchIdx = this.lvMatches.length ? 0 : -1;
          if (this.searchIdx >= 0) this.scrollToMatch();
        });
      } else {
        this.searchJump(1);
      }
    },
    searchJump(dir) {
      const n = this.lvMatches.length;
      if (!n) return;
      this.searchIdx = (this.searchIdx + dir + n) % n;
      this.scrollToMatch();
    },
    scrollToMatch() {
      const idx = this.searchIdx;
      const key = this.lvMatches[idx];
      if (key === undefined) return;
      this.$nextTick(() => {
        const box = this.$refs.box;
        const el = document.getElementById('logline-' + key);
        if (!box || !el) return;
        const br = box.getBoundingClientRect();
        const er = el.getBoundingClientRect();
        box.scrollTop += (er.top - br.top) - 40;
      });
    },
    // ─── live：SSE 实时追踪 ─────────────────────────────────
    connectStream() {
      this.closeStream();
      this.resetBuffer();
      this.paused = false;
      if (!this.lvPod) { this.connected = false; this.loadingTip = '没有可用的运行中 Pod'; return; }
      // 重连 = 重建：清空已渲染行，重新拉取最近 tail 行（搜索词保留，重建后继续高亮）
      this.lines = [];
      this.seq = 0;
      this._pending = [];
      this._raf = null;
      this.followTail = true;
      this.connected = false;
      this.connecting = true;
      this.loadingTip = '正在连接日志流...';
      // 走 SseHub 多路复用（独立页只有这一个主题，仍占 1 条连接）
      const self = this;
      const topic = 'log:' + this.lvProject + ':' + this.lvEnv + ':'
        + this.lvPod + ':' + (this.lvService || '') + ':' + String(this.lvTail);
      this.streamUnsub = SseHub.subscribe(topic, {
        onopen: () => {
          // 连接（重）建 = 重建：清空已渲染行，服务器会重放最近 tail 行
          self.connecting = false;
          self.connected = true;
          self.loadingTip = '';
          self.lines = [];
          self.seq = 0;
          self._pending = [];
          self._raf = null;
          self.scheduleFlush();
        },
        onmessage: (d) => {
          if (d.error) { self.onStreamEnd('[错误] ' + d.error); return; }
          if (d.end) { self.onStreamEnd('── 日志流结束（Pod 退出或重启）──'); return; }
          if (d.line !== undefined) self.receiveLine(d.line);
        },
        onerror: () => {
          self.connected = false;
          self.connecting = false;
        },
      });
    },
    // 流结束/出错：提示行排在积压尾部（有积压时继续按节奏吐），随后断开
    onStreamEnd(text) {
      this.paused = false;
      this.detached = false;
      const line = { k: ++this.seq, t: text };
      if (this._backlog && this._backlog.length) {
        this._backlog.push(line);
        this.backlogCount = this._backlog.length;
        this.startDrain();
      } else {
        this._pending.push(line);
        this.flushBatch();
      }
      this.closeStream();
    },
    // 收到一行：不渲染状态（手动暂停 / 搜索中 / 上滚阅读）→ 只进积压区；
    // 追平积压中 → 排到积压尾部保序；真正跟随时才分批渲染
    receiveLine(text) {
      // 已因积压满额断开：后续帧一律丢弃（连接关闭后正常也不会有新帧）
      if (this.detached) return;
      if (!this._backlog) this._backlog = [];
      const line = { k: ++this.seq, t: text };
      if (this.buffering) {
        this._backlog.push(line);
        this.backlogCount = this._backlog.length;
        if (this.backlogCount >= SVC_LOG_BACKLOG_MAX && !this.detached) {
          // 积压满额：停止追踪，等用户重连（重连会重建并重新拉取内容）
          this.closeStream();
          this.detached = true;
        }
        return;
      }
      if (this._backlog.length) {
        // 还在吐积压：新行排队保序，避免插队导致日志顺序错乱
        this._backlog.push(line);
        if (this._backlog.length > SVC_LOG_BACKLOG_HARD_MAX) {
          this._backlog.splice(0, this._backlog.length - SVC_LOG_BACKLOG_HARD_MAX);
        }
        this.backlogCount = this._backlog.length;
        return;
      }
      this._pending.push(line);
      this.scheduleFlush();
    },
    scheduleFlush() {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => this.flushBatch());
    },
    flushBatch() {
      if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
      const pending = this._pending;
      if (!pending || !pending.length) return;
      this._pending = [];
      this.appendLines(pending);
      if (!this.buffering) this.$nextTick(() => this.scrollToBottom());
    },
    appendLines(list) {
      for (let i = 0; i < list.length; i++) this.lines.push(list[i]);
      // 防内存膨胀：仅保留最近 SVC_LOG_MAX_LINES 行
      if (this.lines.length > SVC_LOG_MAX_LINES) {
        this.lines.splice(0, this.lines.length - SVC_LOG_MAX_LINES);
      }
    },
    // 手动暂停/恢复追踪：只切「是否实时渲染」，SSE 连接始终保留（恢复后按节奏吐积压）
    togglePause() {
      this.paused = !this.paused;
      // 恢复追踪时若已滚离底部，直接回到最新位置（搜索定位中保持原位）
      if (!this.paused && !this.searchWord && !this.followTail) {
        this.$nextTick(() => this.scrollToBottom(true));
      }
    },
    // 点击积压：回到底部 + 立即吐完积压 + 恢复实时渲染（会清空搜索，否则仍处于不渲染态）
    jumpToLive() {
      this.paused = false;
      this.searchInput = '';
      this.searchWord = '';
      this.searchIdx = -1;
      this.stopDrain();
      if (this._backlog && this._backlog.length) {
        this.appendLines(this._backlog.splice(0, this._backlog.length));
        this.backlogCount = 0;
      }
      this.followTail = true;
      this.$nextTick(() => this.scrollToBottom(true));
    },
    startDrain() {
      if (this._drainTimer || this.buffering) return;
      this._drainTimer = setInterval(() => this.drainStep(), SVC_LOG_DRAIN_MS);
    },
    drainStep() {
      if (!this._backlog || !this._backlog.length) { this.stopDrain(); return; }
      if (this.buffering) { this.stopDrain(); return; }
      const batch = this._backlog.splice(0, SVC_LOG_DRAIN_BATCH);
      this.backlogCount = this._backlog.length;
      this.appendLines(batch);
      this.$nextTick(() => this.scrollToBottom());
      if (!this._backlog.length) this.stopDrain();
    },
    stopDrain() {
      if (this._drainTimer) { clearInterval(this._drainTimer); this._drainTimer = null; }
    },
    resetBuffer() {
      this.stopDrain();
      this._backlog = [];
      this._pending = [];
      this.backlogCount = 0;
      this.detached = false;
    },
    closeStream() {
      if (this.streamUnsub) { this.streamUnsub(); this.streamUnsub = null; }
      if (this._raf) { cancelAnimationFrame(this._raf); this._raf = null; }
      this._pending = [];
      this.connected = false;
      this.connecting = false;
    },
    // ─── file：NFS 日志文件内容（流式读取） ─────────────────
    loadFile() {
      this.closeStream();
      this.resetBuffer();
      const gen = ++this._loadGen;
      this.lines = [];
      this.seq = 0;
      this.loading = true;
      this.loadingTip = '加载中...';
      this.followTail = true;
      const url = '/api/deploy/service-info/logfile/content?project=' + encodeURIComponent(this.lvProject)
        + '&env=' + encodeURIComponent(this.lvEnv) + '&service=' + encodeURIComponent(this.lvService)
        + '&file=' + encodeURIComponent(this.lvFile);
      const token = localStorage.getItem('auth_token') || '';
      fetch(url, { headers: { 'Authorization': 'Bearer ' + token } }).then(async (resp) => {
        if (gen !== this._loadGen) return;
        const ct = resp.headers.get('Content-Type') || '';
        if (!resp.ok || ct.indexOf('application/json') !== -1) {
          let msg = '读取文件失败';
          try { msg = (await resp.json()).msg || msg; } catch (e) { /* 忽略解析失败 */ }
          this.loading = false;
          this.loadingTip = msg;
          ElementPlus.ElMessage.error(msg);
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let carry = '';
        let first = true;
        while (true) {
          const r = await reader.read();
          if (r.done) break;
          // 清屏 / 重新加载后丢弃本轮剩余内容
          if (gen !== this._loadGen) return;
          carry += decoder.decode(r.value, { stream: true });
          const idx = carry.lastIndexOf('\n');
          if (idx === -1) continue;
          carry.slice(0, idx).split('\n').forEach(t => this.lines.push({ k: ++this.seq, t: t }));
          carry = carry.slice(idx + 1);
          if (first) { first = false; this.loading = false; }
        }
        if (gen !== this._loadGen) return;
        if (carry) this.lines.push({ k: ++this.seq, t: carry });
        this.loading = false;
        this.loadingTip = '';
        this.$nextTick(() => this.scrollToBottom());
      }).catch(() => {
        if (gen !== this._loadGen) return;
        this.loading = false;
        this.loadingTip = '读取文件失败';
        ElementPlus.ElMessage.error('读取文件失败');
      });
    },
    download() {
      const token = localStorage.getItem('auth_token') || '';
      const params = new URLSearchParams({
        project: this.lvProject, env: this.lvEnv,
        service: this.lvService, file: this.lvFile, token: token,
      });
      window.open('/api/deploy/service-info/logfile/download?' + params.toString());
    },
    reload() {
      if (this.lvType === 'file') this.loadFile();
      else this.connectStream();
    },
    // 清屏：只清当前展示内容，不断开实时流（live）/ 不重新拉文件（file，点「刷新」重新加载）
    clearScreen() {
      this._loadGen++;               // 作废仍在读取中的文件流
      this.lines = [];
      this.searchInput = '';
      this.searchWord = '';
      this.searchIdx = -1;
      this.followTail = true;
      if (this.lvType === 'live') {
        // 丢弃尚未渲染的缓冲行与积压，SSE 连接保持，后续新日志继续追加
        this.resetBuffer();
        this.loadingTip = '';
      } else {
        this.loading = false;
        this.loadingTip = '已清屏，点「刷新」重新加载';
      }
      this.$nextTick(() => this.scrollToBottom(true));
    },
  },
  // 独立标签页不提供「关闭」按钮：由浏览器关闭页签即可
  template: `
  <div class="svc-logview svc-log-dialog">
    <div class="svc-logview-bar">
      <span class="svc-log-title">[[ lvTitle ]]</span>
      <span class="svc-log-count">共 [[ lines.length ]] 行</span>
      <span class="svc-log-status" v-if="lvType === 'live'">
        <span :style="{ width:'8px',height:'8px',borderRadius:'50%',background:streamDotColor }"></span>
        [[ streamStateText ]]
      </span>
      <!-- 重连：仅在连接断开时出现，紧跟状态文字 -->
      <el-button v-if="lvType === 'live' && !connected && !connecting" size="small" @click="reload">重连</el-button>
      <!-- 积压：点击回到底部，立即吐完积压并恢复实时渲染 -->
      <span v-if="lvType === 'live' && backlogCount" class="svc-log-backlog"
            title="点击回到底部并恢复实时渲染（会清空搜索）" @click="jumpToLive">积压 [[ backlogCount ]] 行 ⇩</span>
      <span class="svc-log-header-tools">
        <el-input v-model="searchInput" ref="searchInput" size="small" style="width:240px;" clearable
                  placeholder="搜索（回车定位，Ctrl+F 聚焦）" @clear="commitSearch" @keydown.enter="onSearchEnter">
          <template #prefix><span style="font-size:13px">🔍</span></template>
        </el-input>
        <span v-if="searchWord" style="color:#a8bcc0;font-size:12px;white-space:nowrap">[[ lvMatches.length ? (searchIdx + 1) + '/' + lvMatches.length : '无匹配' ]]</span>
        <el-button v-if="searchWord" size="small" :disabled="!lvMatches.length" @click="searchJump(-1)">↑</el-button>
        <el-button v-if="searchWord" size="small" :disabled="!lvMatches.length" @click="searchJump(1)">↓</el-button>
        <el-button v-if="lvType === 'live'" size="small" :type="paused ? 'warning' : ''" @click="togglePause">[[ paused ? '▶ 恢复追踪' : '⏸ 暂停追踪' ]]</el-button>
        <el-button v-if="lvType === 'file'" size="small" @click="reload">刷新</el-button>
        <el-button v-if="lvType === 'file'" size="small" @click="download">下载</el-button>
        <el-button size="small" @click="clearScreen">清屏</el-button>
        <el-button v-if="showBackToBottom" size="small" @click="scrollToBottom(true)">⇩ 回到底部</el-button>
      </span>
    </div>
    <div class="svc-log-terminal svc-logview-body" ref="box" @scroll="onBoxScroll">
      <div v-if="loading && !lines.length" class="svc-logview-empty">[[ loadingTip || '加载中...' ]]</div>
      <div v-else-if="!lines.length" class="svc-logview-empty">[[ loadingTip || '暂无日志内容' ]]</div>
      <svc-log-lines v-else :lines="lines" :search-word="searchWord" :current-key="lvCurrentKey"></svc-log-lines>
    </div>
  </div>`,
};
