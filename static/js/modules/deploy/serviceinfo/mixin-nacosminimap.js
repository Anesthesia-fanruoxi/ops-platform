// ============================================================
// 服务信息页 mixin：配置弹窗右侧 Minimap 缩略图
// 整份内容等比缩小展示 + 当前视口高亮框；点击/按住拖动可跳转主区滚动
// 主滚动体：查看态 = configPre；编辑态 = configTextarea（单滚动体架构）
// ============================================================

const SVC_MINI_SCALE = 0.3;   // 缩略图缩放系数：pre 字号 12.5px → 约 3.75px/字符

const SvcMixinNacosMinimap = {
  data() {
    return {
      miniShift: 0,      // 缩略内容 translateY（长内容时跟随视口平移，负值）
      miniViewTop: 0,    // 视口指示框 top（px）
      miniViewH: 0,      // 视口指示框高（px）
      miniSbTop: 0,      // 自绘滚动条 thumb top（px）
      miniSbH: 0,        // 自绘滚动条 thumb 高（px）
    };
  },
  computed: {
    svcMiniScale() { return SVC_MINI_SCALE; },
    // 屏幕位移 = scale × pre 坐标系位移，模板绑定换算后的值
    miniShiftScaled() { return this.miniShift / SVC_MINI_SCALE; },
  },
  watch: {
    // 内容/模式/尺寸变化后重建比例（同属性 watch 跨 mixin 合并执行，互不影响）
    configContent() { if (this.configEditorVisible) this.$nextTick(() => this.syncMinimap()); },
    configEditMode() { this.$nextTick(() => this.syncMinimap()); },
    configFullscreen() { this.$nextTick(() => this.syncMinimap()); },
    configEditorVisible(v) {
      if (v) this.$nextTick(() => {
        this.syncMinimap();
        // 弹窗尺寸首帧渲染后行高才稳定，再补一次校准
        setTimeout(() => this.syncMinimap(), 120);
      });
    },
  },
  methods: {
    // ─── Minimap 同步与跳转 ───────────────────────────────
    _cfgScrollEl() {
      return this.configEditMode ? this.$refs.configTextarea : this.$refs.configPre;
    },

    // 主区滚动/内容变化后同步指示框与内容平移（syncCfgGutter 滚动事件内调用）
    syncMinimap() {
      const mm = this.$refs.cfgMinimap;
      const pre = this.$refs.minimapPre;
      const el = this._cfgScrollEl();
      if (!mm || !pre || !el) return;
      const Hc = mm.clientHeight;
      const SH = el.scrollHeight;
      const CH = el.clientHeight;
      if (!Hc || !SH || !CH) return;
      const Hm = pre.offsetHeight * SVC_MINI_SCALE;   // offsetHeight 不受 transform 影响
      const p = el.scrollTop / SH;
      let shift = 0;
      if (Hm > Hc) {
        // 长内容：指示框保持容器居中，内容反向平移（clamp 防止两端越界）
        shift = Math.min(0, Math.max(Hc - Hm, Hc / 2 - p * Hm));
      }
      this.miniShift = shift;
      // 视口框与自绘滚动条 thumb 采用同一“滚动进度”映射，二者始终对齐：
      // top = 进度 × (轨道高 - 自身高)，滚到底时同步贴底（框不再按内容坐标提前到底）
      const scrollable = SH - CH;
      const progress = scrollable > 0 ? el.scrollTop / scrollable : 0;
      const barH = Math.max(24, (CH / SH) * Hc);   // 框高 = Thumb 高（可视占比按轨道高度折算）
      const barTop = progress * (Hc - barH);
      this.miniViewTop = barTop;
      this.miniViewH = barH;
      this.miniSbTop = barTop;
      this.miniSbH = barH;
      // 拖拽选择/滚动时高频触发，直接写 DOM 跳过 Vue patch，保证逐帧跟滚丝滑
      // （data 已同步为同值，Vue diff 无变化不会重写，两者不冲突）
      const miniPre = this.$refs.minimapPre;
      if (miniPre) miniPre.style.transform = 'scale(' + SVC_MINI_SCALE + ') translateY(' + (shift / SVC_MINI_SCALE) + 'px)';
      const view = this.$refs.minimapView;
      if (view) {
        view.style.top = this.miniViewTop + 'px';
        view.style.height = this.miniViewH + 'px';
      }
      const thumb = this.$refs.cfgScrollbarThumb;
      if (thumb) {
        thumb.style.top = this.miniSbTop + 'px';
        thumb.style.height = this.miniSbH + 'px';
      }
    },

    // 自绘滚动条拖拽/点击：点 thumb 抓取拖动，点轨道空白则 thumb 中心对齐点击处
    onSbDown(e) {
      const sb = this.$refs.cfgScrollbar;
      const el = this._cfgScrollEl();
      if (!sb || !el) return;
      const Hc = sb.clientHeight;
      const SH = el.scrollHeight;
      const CH = el.clientHeight;
      if (!Hc || !SH || !CH) return;
      const rect = sb.getBoundingClientRect();
      const y0 = e.clientY - rect.top;
      const thumbH = Math.max(24, (CH / SH) * Hc);
      const maxTop = Math.max(0, Hc - thumbH);
      const offset = (y0 >= this.miniSbTop && y0 <= this.miniSbTop + thumbH) ? (y0 - this.miniSbTop) : thumbH / 2;
      const apply = (ev) => {
        const top = Math.max(0, Math.min(maxTop, ev.clientY - rect.top - offset));
        el.scrollTop = maxTop ? (top / maxTop) * (SH - CH) : 0;
        this.syncMinimap();
      };
      apply(e);
      const up = () => {
        window.removeEventListener('mousemove', apply);
        window.removeEventListener('mouseup', up);
      };
      window.addEventListener('mousemove', apply);
      window.addEventListener('mouseup', up);
    },

    // 点击/按住拖动缩略图 → 主区跳转：进度语义，框中心对齐点击位置（与滚动条/视口框同一坐标系）
    onMinimapDown(e) {
      const mm = this.$refs.cfgMinimap;
      if (!mm) return;
      const jump = (ev) => {
        const rect = mm.getBoundingClientRect();
        const y = ev.clientY - rect.top;
        const el = this._cfgScrollEl();
        if (!el) return;
        const Hc = mm.clientHeight;
        const SH = el.scrollHeight;
        const CH = el.clientHeight;
        const scrollable = SH - CH;
        if (!Hc || !SH || !CH || scrollable <= 0) return;
        const barH = Math.max(24, (CH / SH) * Hc);
        const target = Math.max(0, Math.min(Hc - barH, y - barH / 2));
        el.scrollTop = (target / (Hc - barH)) * scrollable;
        this.syncMinimap();
      };
      jump(e);
      const move = (ev) => jump(ev);
      const up = () => {
        window.removeEventListener('mousemove', move);
        window.removeEventListener('mouseup', up);
      };
      window.addEventListener('mousemove', move);
      window.addEventListener('mouseup', up);
    },
  },
};
