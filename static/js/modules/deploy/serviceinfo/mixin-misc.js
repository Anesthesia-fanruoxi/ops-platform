// ============================================================
// 服务信息页 mixin：杂项小功能
//   - 部署配置弹窗（环境变量子序列过滤 + K8s Deployment YAML 查看）
//   - 选择服务目录弹窗（部署 waiting 时勾选回填流程模板）
//   - copyText 通用复制
// ============================================================

const SvcMixinMisc = {
  data() {
    return {
      // 部署配置弹窗
      envVisible: false, envRows: [], envServiceName: '', envSearchWord: '',
      envLoading: false,     // 环境变量弹窗加载中
      yamlVisible: false,
      yamlFile: '',
      yamlContent: '',
      // 选择服务目录弹窗（部署等待时勾选回填模板）
      selectDirsVisible: false,
      selectDirsPath: '',
      selectDirsEntries: [],
      selectDirsLoading: false,
      selectDirsChecked: {},
      selectDirsList: [],
      selectDirsArtifactDir: '',   // 全局产物目录（各服务内统一子路径），随服务目录一并回填模板
      selectDirsFirstLoad: true,   // 仅首次加载目录时预填产物目录，避免浏览子目录时覆盖用户输入
      selectDirsSaving: false,
    };
  },
  computed: {
    selectDirsSegments() { return this.selectDirsPath ? this.selectDirsPath.split('/').filter(Boolean) : []; },
    selectDirsParent() {
      const segs = this.selectDirsSegments;
      return segs.length > 1 ? segs.slice(0, -1).join('/') : '';
    },
    filteredEnvRows() {
      if (!this.envSearchWord) return this.envRows;
      return this.envRows.filter(r => this.isSubseqMatch(this.envSearchWord, r.name));
    },
  },
  methods: {
    // ─── 部署配置 ─────────────────────────────────────────

    // 子序列匹配（忽略大小写与非字母数字符号）：只匹配变量名
    isSubseqMatch(query, name) {
      const q = String(query || '').toLowerCase().replace(/[^a-z0-9]/g, '');
      const n = String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
      if (!q) return true;
      let qi = 0;
      for (let i = 0; i < n.length && qi < q.length; i++) {
        if (n[i] === q[qi]) qi++;
      }
      return qi === q.length;
    },
    openEnv(svc) {
      this.envServiceName = svc.name;
      this.envRows = [];
      this.envLoading = true;
      this.envVisible = true;
      // 实时读 K8s Deployment spec（设计决策：envs 不再随列表/SSE 携带）
      const url = '/api/deploy/service-info/envs?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(svc.name);
      ajax('GET', url, null, (r) => {
        this.envLoading = false;
        if (r.code === 200 && r.data) {
          this.envRows = (r.data.envs || []).map(e => ({ name: e.name, value: e.value || '', source: e.source || '' }));
        } else {
          // 回退：列表/快照里已有的 envs（YAML 回退路径仍携带）
          this.envRows = (svc.envs || []).map(e => ({ name: e.name, value: e.value || '', source: e.source || '' }));
          ElementPlus.ElMessage.warning((r.msg || '读取环境变量失败') + '，已展示快照数据');
        }
      });
    },
    openYaml(row) {
      const url = '/api/deploy/service-info/yaml?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv) + '&service=' + encodeURIComponent(row.name);
      ajax('GET', url, null, (r) => {
        this.yamlFile = (r.data || {}).file || '';
        this.yamlContent = (r.data || {}).content || '';
        this.yamlVisible = true;
      });
    },

    // ─── 选择服务目录（部署等待时勾选回填模板）─────────────────────────
    openSelectDirsDialog() {
      this.selectDirsChecked = {};
      this.selectDirsList = [];
      this.selectDirsArtifactDir = '';
      this.selectDirsFirstLoad = true;
      this.selectDirsVisible = true;
      this.loadCodeDirs('');
    },
    loadCodeDirs(path) {
      if (!this.bpBuild) return;
      this.selectDirsPath = path || '';
      this.selectDirsLoading = true;
      const params = new URLSearchParams({ path: this.selectDirsPath });
      ajax('GET', '/api/cicd/builds/' + this.bpBuild.id + '/code-dirs?' + params.toString(), null, (r) => {
        this.selectDirsLoading = false;
        if (r.code === 200 && r.data) {
          this.selectDirsEntries = r.data.entries || [];
          if (this.selectDirsFirstLoad) {
            this.selectDirsArtifactDir = r.data.artifact_dir || '';
            this.selectDirsFirstLoad = false;
          }
        } else {
          this.selectDirsEntries = [];
          ElementPlus.ElMessage.error(r.msg || '读取目录失败');
        }
      }, () => { this.selectDirsLoading = false; });
    },
    selectDirJoin(name) {
      return this.selectDirsPath ? this.selectDirsPath + '/' + name : name;
    },
    // 计算 fullPath 相对于「已勾选服务目录」的子路径；无匹配时用首段（服务目录）兜底
    relFromService(fullPath) {
      let rel = fullPath, best = '';
      for (const svc of this.selectDirsList) {
        if (fullPath === svc) { best = svc; rel = ''; break; }
        if (fullPath.startsWith(svc + '/') && svc.length > best.length) { best = svc; rel = fullPath.slice(svc.length + 1); }
      }
      if (!best) {
        const segs = fullPath.split('/');
        rel = segs.length > 1 ? segs.slice(1).join('/') : '';
      }
      return rel;
    },
    // 目录行：设定该目录为产物目录（相对服务目录的子路径）
    setDirAsArtifact(name) {
      const rel = this.relFromService(this.selectDirJoin(name));
      this.selectDirsArtifactDir = rel;
      ElementPlus.ElMessage.success(rel ? ('已设定产物目录：' + rel) : '已设定：收集服务根目录全部内容');
    },
    // 文件行：设定此类文件为产物，按扩展名填入通配符（*.ext 或 *）
    setFileAsArtifact(name) {
      const dirRel = this.relFromService(this.selectDirsPath);
      const dot = name.lastIndexOf('.');
      const wc = dot > 0 ? '*' + name.slice(dot) : '*';
      const val = dirRel ? dirRel + '/' + wc : wc;
      ElementPlus.ElMessageBox.confirm('设定此类文件（' + wc + '）为产物？将填入：' + val, '设定产物', {
        confirmButtonText: '确定', cancelButtonText: '取消', type: 'info'
      }).then(() => {
        this.selectDirsArtifactDir = val;
        ElementPlus.ElMessage.success('已设定产物：' + val);
      }).catch(() => {});
    },
    // 全选/取消全选：全选作用于当前视图 dir 行（打开弹窗默认顶层=全部服务）；取消全选清空所有勾选
    checkAllSelectDirs(val) {
      if (!val) {
        this.selectDirsChecked = {};
        this.selectDirsList = [];
        return;
      }
      this.selectDirsEntries.filter(e => e.type === 'dir').forEach(e => {
        this.toggleSelectDir(this.selectDirJoin(e.name), true);
      });
    },
    toggleSelectDir(name, v) {
      if (v) {
        this.selectDirsChecked[name] = true;
        if (!this.selectDirsList.includes(name)) this.selectDirsList.push(name);
      } else {
        delete this.selectDirsChecked[name];
        const i = this.selectDirsList.indexOf(name);
        if (i > -1) this.selectDirsList.splice(i, 1);
      }
    },
    removeSelectDir(i) {
      const name = this.selectDirsList[i];
      this.selectDirsList.splice(i, 1);
      if (name) delete this.selectDirsChecked[name];
    },
    confirmSelectDirs() {
      if (!this.selectDirsList.length) { ElementPlus.ElMessage.warning('请至少勾选一个服务目录'); return; }
      this.selectDirsSaving = true;
      ajax('POST', '/api/cicd/builds/' + this.bpBuild.id + '/configure-dirs',
        { artifact_dirs: this.selectDirsList.slice(), artifact_dir: (this.selectDirsArtifactDir || '').trim() }, (res) => {
        this.selectDirsSaving = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg || '服务目录已回填到流程模板，请重新触发构建');
          this.selectDirsVisible = false;
          this.loadEnvs();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      }, () => { this.selectDirsSaving = false; });
    },

    // ─── 通用 ─────────────────────────────────────────────

    copyText(text, label) {
      const done = () => ElementPlus.ElMessage.success((label || '内容') + ' 已复制');
      const fallback = () => {
        try {
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          done();
        } catch (e) {
          ElementPlus.ElMessage.warning('复制失败，请手动选择复制');
        }
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(String(text || '')).then(done).catch(fallback);
      } else {
        fallback();
      }
    },
  },
};
