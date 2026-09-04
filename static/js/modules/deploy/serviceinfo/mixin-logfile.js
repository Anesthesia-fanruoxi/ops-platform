// ============================================================
// 服务信息页 mixin：日志目录（SSH 直连 NFS 列出/查看/下载）
//                  + 文件内容查看（流式加载）+ 内容搜索定位（↑/↓ 循环跳转）
// ============================================================

const SvcMixinLogfile = {
  data() {
    return {
      // 日志目录弹窗
      lfVisible: false, lfServiceName: '', lfPods: [], lfPath: '', lfFiles: [], lfLoading: false,
      lfContentVisible: false, lfContentFile: '', lfLines: [], lfContentLoading: false,
      lfSearchWord: '', lfSearchIdx: -1,   // 当前定位的匹配行序号（lfMatchIndices 下标）
    };
  },
  computed: {
    // 日志文件内容匹配行下标数组（流式增量填充，lfLines 变化自动跟随）
    lfMatchIndices() {
      if (!this.lfSearchWord) return [];
      const q = this.lfSearchWord.toLowerCase();
      const out = [];
      this.lfLines.forEach((l, i) => { if (l.toLowerCase().includes(q)) out.push(i); });
      return out;
    },
    lfMatchCount() { return this.lfMatchIndices.length; },
  },
  watch: {
    // 文件内容搜索词变化：重置定位序号（回车/按钮重新从头定位）
    lfSearchWord() { this.lfSearchIdx = -1; },
  },
  methods: {
    openLogFiles(svc) {
      this.lfServiceName = svc.name;
      this.lfPods = svc.pods || [];
      this.lfFiles = [];
      this.lfPath = '';
      this.lfVisible = true;
      this.loadLogFiles();
    },
    // 路径仅展示末两级目录：{项目}-{环境}/{服务目录}
    lfShortPath() {
      const parts = (this.lfPath || '').split('/').filter(Boolean);
      return parts.slice(-2).join('/');
    },
    // 内容弹窗行渲染：复用通用高亮（时间/方法着色 + 搜索高亮）
    lfRenderLine(line) {
      return svcHighlightLine(line, this.lfSearchWord);
    },
    // ─── 文件内容搜索定位（与运行日志弹窗同款：回车跳首个，之后循环 ↑/↓） ──
    onLfSearchEnter() {
      if (!this.lfSearchWord) return;
      if (this.lfSearchIdx === -1 && this.lfMatchIndices.length) {
        this.lfSearchIdx = 0;
        this.lfScrollToMatch();
      } else {
        this.lfSearchJump(1);
      }
    },
    lfSearchJump(dir) {
      const n = this.lfMatchIndices.length;
      if (!n) return;
      this.lfSearchIdx = (this.lfSearchIdx + dir + n) % n;
      this.lfScrollToMatch();
    },
    lfScrollToMatch() {
      const idx = this.lfSearchIdx;
      if (idx < 0 || !this.lfMatchIndices.length) return;
      this.$nextTick(() => {
        const box = this.$refs.lfContentBox;
        if (!box) return;
        const el = document.getElementById('lfline-' + this.lfMatchIndices[idx]);
        if (el) box.scrollTop = el.offsetTop - box.offsetTop - 8;
      });
    },
    isLfCurMatch(i) {
      return this.lfSearchIdx >= 0 && this.lfMatchIndices[this.lfSearchIdx] === i;
    },
    // 超过 20MB 的文件不支持在线查看，仅下载
    lfTooLarge(row) {
      return (row.size || 0) > 20 * 1024 * 1024;
    },
    loadLogFiles() {
      this.lfLoading = true;
      const url = '/api/deploy/service-info/logfiles?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(this.lfServiceName);
      ajax('GET', url, null, (r) => {
        this.lfLoading = false;
        if (r.code === 200 && r.data) {
          this.lfPath = r.data.path || '';
          this.lfFiles = r.data.list || [];
          if (r.data.message) ElementPlus.ElMessage.warning(r.data.message);
        } else {
          ElementPlus.ElMessage.error(r.msg || '读取日志目录失败');
        }
      });
    },
    lfRunningPod(fileName) {
      const pods = (this.lfPods || []).filter(p => p.phase === 'Running' && !p.reason);
      for (const p of pods) {
        if (p.name && fileName.indexOf(p.name) !== -1) return p.name;
      }
      return '';
    },
    viewLogfile(row) {
      if (this.lfTooLarge(row)) {
        ElementPlus.ElMessage.warning('文件大小超过 20MB，不支持在线查看，请下载后查看');
        return;
      }
      this.lfContentFile = row.name;
      this.lfLines = [];
      this.lfSearchWord = '';
      this.lfSearchIdx = -1;
      this.lfContentLoading = true;
      this.lfContentVisible = true;
      const url = '/api/deploy/service-info/logfile/content?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(this.lfServiceName)
        + '&file=' + encodeURIComponent(row.name);
      const token = localStorage.getItem('auth_token') || '';
      fetch(url, { headers: { 'Authorization': 'Bearer ' + token } }).then(async (resp) => {
        const ct = resp.headers.get('Content-Type') || '';
        if (!resp.ok || ct.indexOf('application/json') !== -1) {
          // 错误响应为 JSON
          let msg = '读取文件失败';
          try { msg = (await resp.json()).msg || msg; } catch (e) { /* 忽略解析失败 */ }
          this.lfContentLoading = false;
          this.lfContentVisible = false;
          ElementPlus.ElMessage.error(msg);
          return;
        }
        // 流式读取：边收边按行增量渲染
        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let carry = '';
        let first = true;
        while (true) {
          const r = await reader.read();
          if (r.done) break;
          carry += decoder.decode(r.value, { stream: true });
          const idx = carry.lastIndexOf('\n');
          if (idx === -1) continue;
          this.lfLines.push(...carry.slice(0, idx).split('\n'));
          carry = carry.slice(idx + 1);
          if (first) { first = false; this.lfContentLoading = false; }
        }
        if (carry) this.lfLines.push(carry);
        this.lfContentLoading = false;
        // 加载完成滚动到底部（日志最新内容在末尾）
        this.$nextTick(() => {
          const box = this.$refs.lfContentBox;
          if (box) box.scrollTop = box.scrollHeight;
        });
      }).catch(() => {
        this.lfContentLoading = false;
        this.lfContentVisible = false;
        ElementPlus.ElMessage.error('读取文件失败');
      });
    },
    downloadLogfile(row) {
      const token = localStorage.getItem('auth_token') || '';
      const params = new URLSearchParams({
        project: this.selectedProject, env: this.selectedEnv,
        service: this.lfServiceName, file: row.name, token: token,
      });
      window.open('/api/deploy/service-info/logfile/download?' + params.toString());
    },
  },
};
