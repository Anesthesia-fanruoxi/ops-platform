// ============================================================
// 服务信息页 mixin：Nacos 配置业务（打开/加载/编辑取消/新增/发布 diff/发布）
// 渲染与搜索高亮、YAML 参考线见 mixin-nacosrender.js
// ============================================================

const SvcMixinNacos = {
  data() {
    return {
      // Nacos 配置弹窗
      configEditorVisible: false,
      configRow: null,
      configContent: '',
      configLoading: false,
      configEditMode: false,
      configNotFound: false,
      configIsNew: false,
      configOriginal: '',
      publishing: false,
    };
  },
  computed: {
    cfgLineCount() { return (this.configContent || '').split(String.fromCharCode(10)).length; },
    canUpdateNacos() {
      return this.$auth.hasPermission('op:nacos_config_update');
    },
  },
  created() {
    // 查看模式下 Ctrl+F 聚焦弹窗内搜索框；Ctrl+A 仅选中内容区（编辑模式走 textarea 原生全选）
    this._cfgKeyHandler = (e) => {
      if (!this.configEditorVisible || this.configEditMode) return;
      const combo = e.ctrlKey || e.metaKey;
      if (!combo) return;
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        const inp = this.$refs.configSearchInput;
        if (inp && inp.focus) inp.focus();
      } else if ((e.key === 'a' || e.key === 'A') && !this.configNotFound) {
        const pre = this.$refs.configPre;
        if (pre) {
          e.preventDefault();
          const sel = window.getSelection();
          sel.removeAllRanges();
          sel.selectAllChildren(pre);
        }
      }
    };
    document.addEventListener('keydown', this._cfgKeyHandler);
  },
  beforeUnmount() {
    if (this._cfgKeyHandler) {
      document.removeEventListener('keydown', this._cfgKeyHandler);
      this._cfgKeyHandler = null;
    }
  },
  methods: {
    // ─── Nacos 配置 ───────────────────────────────────────

    // 点击直接展示 {服务名}.yaml 配置内容（无列表/搜索）
    openGlobalNacos() {
      this.configRow = { dataId: 'application.yaml', group: 'DEFAULT_GROUP' };
      this.configContent = '';
      this.configEditMode = false;
      this.configSearch = '';
      this.configSearchInput = '';
      this.cfgSearchIdx = -1;
      this.matchCount = 0;
      this.configFullscreen = false;
      this.configOriginal = '';
      this.configNotFound = false;
      this.configIsNew = false;
      this.diffVisible = false;
      this.diffRows = [];
      this.diffStats = { added: 0, removed: 0, modified: 0 };
      this.configEditorVisible = true;
      this.loadConfigContent();
    },
    openNacos(row) {
      this.configRow = { dataId: (row.name || '') + '.yaml', group: 'DEFAULT_GROUP' };
      this.configContent = '';
      this.configEditMode = false;
      this.configSearch = '';
      this.configSearchInput = '';
      this.cfgSearchIdx = -1;
      this.matchCount = 0;
      this.configFullscreen = false;
      this.configOriginal = '';
      this.configNotFound = false;
      this.configIsNew = false;
      this.diffVisible = false;
      this.diffRows = [];
      this.diffStats = { added: 0, removed: 0, modified: 0 };
      this.configEditorVisible = true;
      this.loadConfigContent();
    },
    loadConfigContent() {
      if (!this.configRow) return;
      this.configLoading = true;
      const url = '/api/deploy/service-info/nacos/config?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv)
        + '&dataId=' + encodeURIComponent(this.configRow.dataId)
        + '&group=' + encodeURIComponent(this.configRow.group || 'DEFAULT_GROUP')
        + (this.configRow && this.configRow.global ? '&global=1' : '');
      ajax('GET', url, null, (r) => {
        this.configLoading = false;
        if (r.code === 200) {
          this.configContent = (r.data || {}).content || '';
          this.configOriginal = this.configContent;
          this.configNotFound = false;
          this.configIsNew = false;
        } else if (r.code === 404) {
          // 配置不存在：引导新增
          this.configContent = '';
          this.configOriginal = '';
          this.configNotFound = true;
        } else {
          ElementPlus.ElMessage.error(r.msg || '加载配置失败');
        }
      });
    },
    onConfigDialogClose() {
      this.configEditMode = false;
      this.configSearch = '';
      this.configSearchInput = '';
      this.cfgSearchIdx = -1;
      this.matchCount = 0;
      this.configFullscreen = false;
      this.configNotFound = false;
      this.diffVisible = false;
    },

    // 取消编辑：新增态（配置原本不存在）回退到空状态引导
    cancelConfigEdit() {
      this.configEditMode = false;
      if (this.configIsNew) {
        this.configContent = '';
        this.configNotFound = true;
      }
    },

    // 配置不存在时新增：dataId 已自动生成（{服务名}.yaml），内容从空开始
    createNewConfig() {
      this.configOriginal = '';
      this.configContent = '';
      this.configNotFound = false;
      this.configEditMode = true;
      this.configIsNew = true;
    },

    // 发布前先弹出行级 diff 对比（参考 Nginx 配置保存对比逻辑）；新增配置无旧内容，不对比直接发布
    publishConfig() {
      if (!this.configRow) return;
      if (this.configIsNew) {
        this.doPublish();
        return;
      }
      const diff = this._computeDiff(
        (this.configOriginal || '').split('\n'),
        (this.configContent || '').split('\n'),
      );
      if (!diff.stats.added && !diff.stats.removed && !diff.stats.modified) {
        ElementPlus.ElMessage.warning('内容没有变化，无需发布');
        return;
      }
      this.diffRows = diff.rows;
      this.diffStats = diff.stats;
      this.diffVisible = true;
    },
    doPublish() {
      this.publishing = true;
      ajax('POST', '/api/deploy/service-info/nacos/config', {
        project: this.selectedProject,
        env: this.selectedEnv,
        dataId: this.configRow.dataId,
        group: this.configRow.group || 'DEFAULT_GROUP',
        content: this.configContent,
        global: !!(this.configRow && this.configRow.global),
      }, (r) => {
        this.publishing = false;
        if (r.code === 200) {
          ElementPlus.ElMessage.success('配置已发布');
          this.diffVisible = false;
          this.configOriginal = this.configContent;
          this.configIsNew = false;
          this.configEditMode = false;
        } else {
          ElementPlus.ElMessage.error(r.msg || '发布失败');
        }
      });
    },
  },
};
