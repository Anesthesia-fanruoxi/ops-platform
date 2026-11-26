// ============================================================
// 服务信息页 mixin：Apollo 配置（按 appId=服务名 读取/编辑/发布）
// 复用 Nacos 配置弹窗：内容为 key=value 文本，diff 后一次发布 release
// ============================================================

const SvcMixinApollo = {
  data() {
    return {
      apolloError: '',
      apolloNamespaces: [],
    };
  },
  computed: {
    canUpdateApollo() {
      return this.$auth.hasPermission('op:apollo_config_update');
    },
    canUpdateCurrentConfig() {
      if (this.configRow && this.configRow.apollo) return this.canUpdateApollo;
      return this.canUpdateNacos;
    },
  },
  methods: {
    openApollo(svc) {
      this.configRow = { apollo: true, serviceName: svc.name, appId: svc.name, namespace: '', namespaceId: 0, dataId: svc.name };
      this.apolloError = '';
      this.apolloNamespaces = [];
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
      this.configMapKeys = [];
      this.configEditorVisible = true;
      this.loadApolloContent('');
    },
    loadApolloContent(ns) {
      if (!this.configRow || !this.configRow.apollo) return;
      this.configLoading = true;
      this.apolloError = '';
      const url = '/api/deploy/service-info/apollo/config?project=' + encodeURIComponent(this.selectedProject)
        + '&env=' + encodeURIComponent(this.selectedEnv)
        + '&service=' + encodeURIComponent(this.configRow.serviceName || this.configRow.dataId)
        + '&namespace=' + encodeURIComponent(ns || '');
      ajax('GET', url, null, (r) => {
        this.configLoading = false;
        if (r.code === 200) {
          const d = r.data || {};
          this.configRow.appId = d.appId || this.configRow.appId;
          this.configRow.isPublic = !!d.isPublic;
          this.configRow.namespace = d.namespace || ns || '';
          this.configRow.namespaceId = 0;
          this.configRow.env = d.env || '';
          this.apolloNamespaces = d.namespaces || [];
          this.configContent = d.content || '';
          this.configOriginal = this.configContent;
          this.configNotFound = false;
          this.configIsNew = false;
          this.apolloError = '';
        } else if (r.code === 404) {
          this.configContent = '';
          this.configOriginal = '';
          this.configNotFound = true;
          this.apolloError = r.msg || 'Apollo 中不存在该应用或 namespace';
        } else {
          this.configContent = '';
          this.configOriginal = '';
          this.configNotFound = true;
          this.apolloError = r.msg || '加载 Apollo 配置失败';
        }
      });
    },
    onApolloNsChange(ns) {
      if (this.configEditMode) return;
      this.loadApolloContent(ns);
    },
    doPublishApollo() {
      this.publishing = true;
      ajax('POST', '/api/deploy/service-info/apollo/config', {
        project: this.selectedProject,
        env: this.selectedEnv,
        service: this.configRow.serviceName || this.configRow.dataId,
        namespace: this.configRow.namespace,
        content: this.configContent,
      }, (r) => {
        this.publishing = false;
        if (r.code === 200) {
          const d = r.data || {};
          ElementPlus.ElMessage.success('Apollo 配置已发布（新增 ' + (d.created || 0)
            + '，修改 ' + (d.updated || 0) + '，删除 ' + (d.deleted || 0) + '）');
          this.diffVisible = false;
          this.configOriginal = this.configContent;
          this.configEditMode = false;
          this.loadApolloContent(this.configRow.namespace);
        } else {
          ElementPlus.ElMessage.error(r.msg || '发布失败');
          // 可能部分配置项已写入但发布失败：重新加载，避免界面与 Apollo 实际内容不一致
          this.loadApolloContent(this.configRow.namespace);
        }
      });
    },
  },
};