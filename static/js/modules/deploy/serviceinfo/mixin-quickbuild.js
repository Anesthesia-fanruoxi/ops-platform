// ============================================================
// 服务信息页 mixin：快捷部署构建弹窗（与环境信息页构建弹窗完全一致：
// 分支平铺/目录树选择 + 最近分支 + 服务范围勾选 + 触发构建）
// ============================================================

const SvcMixinQuickBuild = {
  data() {
    return {
      // 快捷部署弹窗（与环境信息页构建弹窗完全一致：分支/服务/类型 + 进度抽屉）
      buildDialogVisible: false,
      buildType: 'backend',
      buildEnv: null,
      buildBranch: '',
      branchOptions: [],
      branchFiltered: [],
      branchLoading: false,
      recentBranches: [],
      recentBranchesFiltered: [],
      serviceToggles: {},
      serviceOptions: [],
      servicesLoaded: false,
      buildTriggering: false,
      branchTreeMode: false,  // 分支展示：false=平铺列表，true=按目录树形
      branchTreeFilter: '',
      branchSearch: '',   // 平铺分支输入框：选择/过滤（回车直接采用输入值）
    };
  },
  computed: {
    selectedServiceCount() {
      return this.serviceOptions.filter(s => this.serviceToggles[s]).length;
    },
    // 全部勾选状态：所有服务开关都开启时为 true（供「全部勾选」开关联动）
    allServicesChecked() {
      return this.serviceOptions.length > 0 && this.serviceOptions.every(s => this.serviceToggles[s]);
    },
    // 输入框关键字：仅手动输入时过滤（回填为 placeholder，不参与过滤）
    branchKw() {
      return (this.branchSearch || '').trim().toLowerCase();
    },
    // 点击输入框：清空默认分支提示（placeholder 自动消失），开始输入即过滤
    onBranchFocus() {
      this.branchSearch = '';
    },
    // 最近分支分组（最近构建选择过的分支，过滤后置顶；最多 5 个）
    branchRecentList() {
      const kw = this.branchKw;
      const list = kw
        ? this.recentBranches.filter(b => this.subsequenceMatch(b.toLowerCase(), kw))
        : this.recentBranches.slice();
      return list.slice(0, 5);
    },
    // 全部分支分组（过滤后，排除已在最近分支组内的，避免重复）
    branchAllList() {
      const kw = this.branchKw;
      const recent = this.recentBranches;
      const list = kw
        ? this.branchOptions.filter(b => this.subsequenceMatch(b.toLowerCase(), kw))
        : this.branchOptions.slice();
      return list.filter(b => !recent.includes(b));
    },
    // 分支目录树：按 / 分层构建（feature/release/hotfix 等目录可展开收起）
    branchTree() {
      const map = {};
      const tree = [];
      (this.branchOptions || []).forEach(b => {
        const parts = b.split('/');
        let level = tree;
        let path = '';
        parts.forEach((p, i) => {
          path = path ? path + '/' + p : p;
          if (i === parts.length - 1) {
            // 叶子 = 分支（完整路径）
            level.push({ key: 'branch-' + b, label: b, branch: b, isBranch: true });
            return;
          }
          let node = map[path];
          if (!node) {
            node = { key: 'dir-' + path, label: p, children: [] };
            map[path] = node;
            level.push(node);
          }
          level = node.children;
        });
      });
      return tree;
    },
  },
  watch: {
    branchTreeFilter(v) {
      this.$refs.branchTreeRef && this.$refs.branchTreeRef.filter(v);
    },
  },
  methods: {
    // ═══════════ 快捷部署（与环境信息页构建弹窗完全一致） ═══════════
    _buildPrefKey(envId) { return 'cicd_build_pref_' + envId; },
    _buildPrefLoad(envId) {
      try {
        const raw = localStorage.getItem(this._buildPrefKey(envId));
        return raw ? JSON.parse(raw) : null;
      } catch (e) { return null; }
    },
    _buildPrefSave() {
      if (!this.buildEnv || !this.buildEnv.id) return;
      const enabled = this.serviceOptions.filter(s => this.serviceToggles[s]);
      try {
        localStorage.setItem(this._buildPrefKey(this.buildEnv.id), JSON.stringify({
          branch: this.buildBranch,
          services: enabled
        }));
      } catch (e) { /* 忽略存储异常 */ }
    },
    openDeploy() {
      // 实时从环境列表取当前选中环境（避免 selectedEnvData 未同步导致误报）
      const env = this.envList.find(e => e.environment === this.selectedEnv) || this.selectedEnvData;
      if (!env || !env.id) { ElementPlus.ElMessage.warning('请先选择环境'); return; }
      this.buildType = 'backend';
      this.openBuildDialog(env, 'backend');
    },
    onDeployTypeChange() {
      if (!this.buildEnv || !this.buildEnv.id) return;
      this.openBuildDialog(this.buildEnv, this.buildType);
    },
    // 点击构建：立即弹窗（分支 git ls-remote 可能 1s+，异步加载不阻塞弹窗）
    openBuildDialog(row, type) {
      this.buildType = (type === 'frontend') ? 'frontend' : 'backend';
      this.buildEnv = row;
      if (!row.project_id) { ElementPlus.ElMessage.warning('缺少项目信息'); return; }

      this._initBuildDialog(row);
      this.buildDialogVisible = true;
      if (this.buildType === 'backend') this._loadBuildServices(row);
      // 分支异步加载：git ls-remote 到远程 Git（网络往返，约 1s），期间弹窗已可操作
      this.branchLoading = true;
      ajax('GET', '/api/cicd/builds/branches?project_id=' + row.project_id + '&project_type=' + this.buildType, null, (r) => {
        this.branchLoading = false;
        if (r.code === 200) {
          let branches = r.data || [];
          const lastBranch = (row.builds && row.builds[this.buildType] && row.builds[this.buildType].branch) || '';
          if (lastBranch && !branches.includes(lastBranch)) branches.unshift(lastBranch);
          this.branchOptions = branches;
          this.branchFiltered = branches;
        } else if (r.code === 400) {
          // 模板未配置 Git 地址：提示并收起弹窗（避免空分支弹窗）
          this.buildDialogVisible = false;
          ElementPlus.ElMessage.error(r.msg || r.message || '该项目未配置模板');
        } else {
          // 网络/服务异常（如 git 拉取失败）：保留弹窗，分支可手动输入
          ElementPlus.ElMessage.error((r.msg || r.message || '获取分支失败') + '，可手动输入分支');
        }
      }, () => { this.branchLoading = false; });
    },
    // 初始化构建弹窗状态（恢复上次偏好 + 最近使用分支）
    _initBuildDialog(row) {
      const pref = this._buildPrefLoad(row.id);
      const lastBranch = (row.builds && row.builds[this.buildType] && row.builds[this.buildType].branch) || '';
      // 回填最后一次执行的分支（最近构建分支优先，其次上次选择，兜底 master）；
      // 输入框以浅色 placeholder 提示该分支，不写入值（不过滤列表，不动直接应用）
      this.buildBranch = lastBranch || (pref && pref.branch) || 'master';
      this.branchSearch = '';
      this.recentBranches = [];
      this.recentBranchesFiltered = [];
      this.serviceToggles = {};
      this.serviceOptions = [];
      this.servicesLoaded = false;
      if (row.id) {
        ajax('GET', '/api/cicd/builds?environment_id=' + row.id, null, (r) => {
          if (r.code === 200) {
            const seen = new Set();
            const recent = [];
            (r.data || []).forEach(b => {
              if (b.branch && !seen.has(b.branch)) { seen.add(b.branch); recent.push(b.branch); }
            });
            this.recentBranches = recent.slice(0, 5);
            this.recentBranchesFiltered = this.recentBranches;
          }
        });
      }
    },
    // 加载服务列表（默认全部开启；上次为部分构建时恢复勾选）
    _loadBuildServices(row) {
      const pref = this._buildPrefLoad(row.id);
      ajax('GET', '/api/cicd/builds/services?project_id=' + row.project_id, null, (r) => {
        this.servicesLoaded = true;
        if (r.code === 200) {
          this.serviceOptions = r.data || [];
          const toggles = {};
          if (pref && Array.isArray(pref.services) && pref.services.length) {
            this.serviceOptions.forEach(s => { toggles[s] = pref.services.includes(s); });
            if (!this.serviceOptions.some(s => toggles[s])) {
              this.serviceOptions.forEach(s => { toggles[s] = true; });
            }
          } else {
            this.serviceOptions.forEach(s => { toggles[s] = true; });
          }
          this.serviceToggles = toggles;
        }
      }, () => { this.servicesLoaded = true; });
    },
    subsequenceMatch(text, keyword) {
      let i = 0;
      for (let j = 0; j < text.length && i < keyword.length; j++) {
        if (text[j] === keyword[i]) i++;
      }
      return i >= keyword.length;
    },
    filterBranches(query) {
      const kw = (query || '').trim().toLowerCase();
      if (!kw) {
        this.branchFiltered = this.branchOptions;
        this.recentBranchesFiltered = this.recentBranches;
        return;
      }
      this.branchFiltered = this.branchOptions.filter(b => this.subsequenceMatch(b.toLowerCase(), kw));
      this.recentBranchesFiltered = this.recentBranches.filter(b => this.subsequenceMatch(b.toLowerCase(), kw));
    },
    onBranchDrop(visible) {
      if (visible) {
        this.branchFiltered = this.branchOptions;
        this.recentBranchesFiltered = this.recentBranches;
        // 打开下拉从顶部开始，不定位到当前选中分支
        this.$nextTick(() => {
          document.querySelectorAll('.el-select-dropdown__wrap').forEach(w => { w.scrollTop = 0; });
        });
      }
    },
    toggleAllServices(val) {
      this.serviceOptions.forEach(s => { this.serviceToggles[s] = !!val; });
    },
    // 输入框回车：直接采用输入值作为分支（用于自定义/快速选择）
    applyBranchInput() {
      const v = (this.branchSearch || '').trim();
      if (v) this.buildBranch = v;
    },
    // 该分支是否为最近构建选择过的分支（置顶 + 标记）
    isRecentBranch(b) {
      return this.recentBranches.includes(b);
    },
    // 树形选择分支：叶子设置 buildBranch；目录节点由 el-tree 自动展开/收起
    onBranchNodeClick(data) {
      if (data && data.isBranch) {
        this.buildBranch = data.branch;
      }
    },
    filterBranchTree(value, data) {
      if (!value) return true;
      if (data.isBranch) return data.branch.toLowerCase().includes(value.toLowerCase());
      return (data.children || []).some(c => this.filterBranchTree(value, c));
    },
    executeBuild() {
      if (!this.buildBranch.trim()) { ElementPlus.ElMessage.warning('请选择或输入分支'); return; }
      let services = [];
      if (this.serviceOptions.length > 1) {
        services = this.serviceOptions.filter(s => this.serviceToggles[s]);
        if (!services.length) { ElementPlus.ElMessage.warning('请至少开启一个要构建的服务'); return; }
      }
      this.buildTriggering = true;
      const env = this.buildEnv;
      this._buildPrefSave();
      ajax('POST', '/api/cicd/builds/trigger', {
        project_id: env.project_id,
        environment_id: env.id,
        branch: this.buildBranch.trim(),
        services: services,
        project_type: this.buildType
      }, (res) => {
        this.buildTriggering = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success('构建已触发');
          this.buildDialogVisible = false;
          this.loadEnvs();
          this.loadServices();
        } else {
          ElementPlus.ElMessage.error(res.msg || '触发失败');
        }
      }, () => { this.buildTriggering = false; });
    },
  },
};
