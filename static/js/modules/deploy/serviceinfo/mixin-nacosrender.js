// ============================================================
// 服务信息页 mixin：Nacos 配置内容渲染（hljs 语法高亮 + 搜索 mark 高亮）
//                  + 搜索定位（↑/↓）+ YAML 段落缩进参考线 + 编辑态渲染/滚动同步
// ============================================================

const SvcMixinNacosRender = {
  data() {
    return {
      configSearchInput: '',   // 搜索输入框实时值（不触发渲染）
      configSearch: '',        // 已提交的搜索词（回车/点🔍 才触发高亮渲染）
      matchCount: 0,
      cfgSearchIdx: -1,        // 当前高亮匹配的序号（0 基，用于 ↑/↓ 切换）
      configFullscreen: false, // Nacos 配置弹窗全屏
      cfgGuides: [],          // YAML 段落缩进参考线（每段一根竖线）
    };
  },
  watch: {
    configContent() {
      if (!this.configEditorVisible) return;
      if (this.configEditMode) this.renderEditView();
      else this.renderConfigView();
    },
    configSearch() {
      if (!this.configEditMode) this.renderConfigView();
    },
    configEditMode(v) {
      if (v) this.renderEditView();
      else this.renderConfigView();
    },
  },
  methods: {
    // ─── 配置查看渲染：hljs 语法高亮 + 搜索关键字 mark 高亮 ───────

    renderConfigView() {
      this.$nextTick(() => {
        const code = this.$refs.configCode;
        if (!code) return;
        code.innerHTML = this._highlightHtml(this.configContent || '');
        this.buildCfgGuides(this.$refs.configPre);

        // 搜索高亮：遍历文本节点包裹 mark（不破坏 hljs 标签）
        this.matchCount = 0;
        const kw = (this.configSearch || '').trim();
        if (kw) {
          const lowerKw = kw.toLowerCase();
          const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT, null);
          const nodes = [];
          while (walker.nextNode()) nodes.push(walker.currentNode);
          nodes.forEach((node) => {
            const txt = node.nodeValue;
            const lower = txt.toLowerCase();
            let idx = lower.indexOf(lowerKw);
            if (idx === -1) return;
            const frag = document.createDocumentFragment();
            let last = 0;
            while (idx !== -1) {
              frag.appendChild(document.createTextNode(txt.slice(last, idx)));
              const mark = document.createElement('mark');
              mark.className = 'svc-search-mark';
              mark.textContent = txt.slice(idx, idx + kw.length);
              frag.appendChild(mark);
              this.matchCount++;
              last = idx + kw.length;
              idx = lower.indexOf(lowerKw, last);
            }
            frag.appendChild(document.createTextNode(txt.slice(last)));
            node.parentNode.replaceChild(frag, node);
          });
        }
      });
    },

    // 聚焦当前第 idx 处匹配：清除旧高亮、滚动到目标（idx<0 跳到首个）
    _focusCfgMatch(idx) {
      const code = this.$refs.configCode;
      if (!code) return;
      const marks = Array.from(code.querySelectorAll('mark.svc-search-mark'));
      if (!marks.length) { this.matchCount = 0; this.cfgSearchIdx = -1; return; }
      marks.forEach((m) => m.classList.remove('svc-search-active'));
      const i = ((idx % marks.length) + marks.length) % marks.length;
      marks[i].classList.add('svc-search-active');
      this.cfgSearchIdx = i;
      this.matchCount = marks.length;
      marks[i].scrollIntoView({ behavior: 'smooth', block: 'center' });
    },

    // 提交搜索：回车 / 点🔍 / 清空 触发。configSearch 变化 → renderConfigView 重建 mark
    commitConfigSearch() {
      const kw = (this.configSearchInput || '').trim();
      this.configSearch = kw;
      this.cfgSearchIdx = -1;
      if (kw) this.$nextTick(() => this._focusCfgMatch(0));
      else { this.matchCount = 0; }
    },
    // 回车：输入有改动 → 提交并跳首个；无改动 → 跳下一个
    onConfigSearchEnter() {
      if (this.configSearchInput !== this.configSearch) this.commitConfigSearch();
      else this.cfgSearchJump(1);
    },
    cfgSearchJump(dir) {
      if (!this.configSearch) return;
      this.$nextTick(() => {
        const base = this.cfgSearchIdx < 0 ? 0 : this.cfgSearchIdx;
        this._focusCfgMatch(base + dir);
      });
    },

    // 配置弹窗全屏切换
    toggleConfigFullscreen() {
      this.configFullscreen = !!this.configFullscreen ? false : true;
    },

    // 编辑态快捷键：Ctrl+/ 注释 / 反注释选中的行（未选区则针对光标所在行）
    onConfigAreaKeydown(e) {
      const ev = e || window.event;
      if (ev.ctrlKey && (ev.key === '/' || ev.key === '?')) {   // 兼容 Shift+/ 打出 '?'
        ev.preventDefault();
        this.toggleCfgComment();
      }
    },
    toggleCfgComment() {
      const ta = this.$refs.configTextarea;
      if (!ta) return;
      const content = this.configContent || '';
      const s = Math.min(ta.selectionStart, ta.selectionEnd);
      const ed = Math.max(ta.selectionStart, ta.selectionEnd);
      const lines = content.split('\n');
      const ns = [0];
      for (let i = 0; i < content.length; i++) if (content.charCodeAt(i) === 10) ns.push(i + 1);
      const lineAt = (pos) => { let lo = 0, hi = ns.length - 1; while (lo < hi) { const m = (lo + hi + 1) >> 1; if (ns[m] <= pos) lo = m; else hi = m - 1; } return lo; };
      let a = lineAt(s);
      let b = lineAt(ed);
      // 选区终点正好是某行行首（不含该行字符）时，退回到上一行，避免误吞空行
      if (b > a && ns[b] >= ed) b--;
      if (b > a && ns[b] >= ed) b--;
      const slice = lines.slice(a, b + 1);
      const allCommented = slice.length > 0 && slice.every((l) => /^\s*#/.test(l));
      const mapped = slice.map((l) => {
        if (allCommented) { const m = l.match(/^(\s*)#\s?/); return m ? (m[1] + l.slice(m[0].length)) : l; }
        return '# ' + l;
      });
      lines.splice(a, mapped.length, ...mapped);
      const newVal = lines.join('\n');
      this.configContent = newVal;    // watcher → renderEditView 实时刷新高亮
      this.$nextTick(() => {
        const t = this.$refs.configTextarea;
        if (!t) return;
        const n2 = [0];
        for (let i = 0; i < newVal.length; i++) if (newVal.charCodeAt(i) === 10) n2.push(i + 1);
        const start = n2[a] != null ? n2[a] : newVal.length;
        const end = (a + mapped.length <= n2.length - 1) ? (n2[a + mapped.length] - 1) : newVal.length;
        t.focus();
        t.setSelectionRange(Math.min(start, newVal.length), Math.min(end, newVal.length));
      });
    },

    escapeHtml(s) {
      return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },

    _highlightHtml(text) {
      let html = '';
      if (window.hljs) {
        try { html = window.hljs.highlight(text, { language: 'yaml' }).value; } catch (e) { html = ''; }
      }
      if (!html) html = this.escapeHtml(text);
      return html;
    },

    // ─── YAML 段落缩进参考线 ───────────────────────────────
    // 按行缩进切出每个「有子行的块」：竖线列取段落自身 key 的起始列，线头从该 key 的
    // 下方一行引出并引到本段末行——不压段落自身及后续同级子 key 的首字符；层级越深颜色越淡
    // withPad：宿主是否含 padding（查看态 pre=true；编辑态 canvas 已在 pre 的 content 区内=false）
    buildCfgGuides(host, withPad = true) {
      const text = this.configContent || '';
      if (!text || !host) { this.cfgGuides = []; return; }
      const cs = window.getComputedStyle(host);
      const fontPx = parseFloat(cs.fontSize) || 12.5;
      let lineH = parseFloat(cs.lineHeight) || 0;
      if (lineH && lineH < fontPx) lineH *= fontPx;   // 部分浏览器返回倍数（1.7）而非像素
      const charW = this._cfgCharWidth(host);
      if (!lineH || !charW) { this.cfgGuides = []; return; }
      const padTop = parseFloat(cs.paddingTop) || 0;
      const padLeft = parseFloat(cs.paddingLeft) || 0;

      const lines = text.split('\n');
      const indentOf = (s) => {
        let n = 0;
        for (const ch of s) {
          if (ch === ' ') n += 1;
          else if (ch === '\t') n += 4;      // 制表符按 4 列折算
          else break;
        }
        return n;
      };

      const segs = [];
      const stack = [];                       // { indent, line, child, depth }
      let lastContent = 0;                    // 最后一行非空行（块收尾时用）
      const close = (s, end) => {
        // 线头从段落自身 key 的「下方一行」引出，列取该 key 的起始列 → 竖线不压任何文字
        if (s.child == null || end <= s.line) return;
        segs.push({ start: s.line + 1, end, col: s.indent, depth: s.depth });
      };
      for (let i = 0; i < lines.length; i++) {
        if (!lines[i].trim()) continue;
        const ind = indentOf(lines[i]);
        lastContent = i;
        while (stack.length && ind <= stack[stack.length - 1].indent) close(stack.pop(), i - 1);
        const parent = stack[stack.length - 1];
        if (parent && parent.child == null) { parent.child = ind; }   // 首个更深行 → 有子行
        stack.push({ indent: ind, line: i, child: null, depth: stack.length });
      }
      while (stack.length) close(stack.pop(), lastContent);

      this.cfgGuides = segs.map((s) => ({
        depth: s.depth,
        style: {
          left: ((withPad ? padLeft : 0) + s.col * charW).toFixed(1) + 'px',
          top: ((withPad ? padTop : 0) + s.start * lineH).toFixed(1) + 'px',
          height: ((s.end - s.start + 1) * lineH).toFixed(1) + 'px',
        },
      }));
    },

    // 等宽字体单字符宽度：隐藏探针实测（两种字体族/字号下都准），结果缓存
    _cfgCharWidth(pre) {
      if (svcCfgCharW) return svcCfgCharW;
      const probe = document.createElement('span');
      probe.textContent = '0000000000000000';
      probe.style.cssText = 'position:absolute;left:-9999px;top:-9999px;white-space:pre;visibility:hidden;';
      pre.appendChild(probe);
      const w = probe.getBoundingClientRect().width / 16;
      pre.removeChild(probe);
      if (w > 0) svcCfgCharW = w;
      return w;
    },

    // 编辑模式高亮层渲染：内容必须与 textarea 完全一致（含末尾换行），否则高亮文字与光标错位
    renderEditView() {
      this.$nextTick(() => {
        const code = this.$refs.configCodeEdit;
        if (!code) return;
        const text = this.configContent || '';
        code.innerHTML = this._highlightHtml(text);
        // 兼底：hljs 异常丢字符时放弃高亮保对齐（文本一致是两层重合的前提）
        if (code.textContent !== text) code.textContent = text;
        this.buildCfgGuides(code.parentNode, false);
        // 重建后按当前滚动位置回填 transform（canvas 本体不重建，transform 保留，此处仅兑底）
        this.syncCfgGutter('edit');
      });
    },

    // textarea 滚动同步：gutter 用 scrollTop；编辑态 canvas 用 transform 平移
    // （scrollTop 赋值会被 clamp 导致失步，transform 数学精确，从根上消除重影/光标错行）
    syncCfgGutter(src) {
      const gutter = this.$refs.cfgGutter;
      const el = src === 'pre' ? this.$refs.configPre : this.$refs.configTextarea;
      if (!el) return;
      if (gutter) gutter.scrollTop = el.scrollTop;
      if (src === 'edit' && this.$refs.cfgCanvas) {
        this.$refs.cfgCanvas.style.transform = 'translate(' + (-el.scrollLeft) + 'px,' + (-el.scrollTop) + 'px)';
      }
      if (this.syncMinimap) this.syncMinimap();   // minimap 跟随主区滚动（mixin-nacosminimap）
    },

    // 内容框右上角复制：复制完整配置内容
    copyConfigContent() {
      const text = this.configContent || '';
      const done = () => ElementPlus.ElMessage.success('已复制到剪贴板');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done).catch(() => this._fallbackCopy(text, done));
      } else {
        this._fallbackCopy(text, done);
      }
    },
    _fallbackCopy(text, done) {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand('copy');
        done();
      } catch (e) {
        ElementPlus.ElMessage.error('复制失败');
      }
      document.body.removeChild(ta);
    },
  },
};
