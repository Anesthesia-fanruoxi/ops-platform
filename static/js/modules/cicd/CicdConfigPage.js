const CicdConfigPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
<div class="card cicd-page">
  <div class="page-header">
    <div class="section-title">CI/CD 管理</div>
  </div>

  <el-tabs v-model="activeTab" @tab-change="onTabChange">
    <!-- ═══ 流程模板 ═══ -->
    <el-tab-pane label="流程模板" name="templates">
      <div class="tpl-toolbar">
        <span class="tpl-toolbar-count">共 <strong>[[ templates.length ]]</strong> 个模板</span>
        <el-button type="primary" size="small" @click="openTemplateForm(null)">+ 新增模板</el-button>
      </div>
      <div v-loading="loadingTemplates" class="cred-grid">
        <div v-for="t in templates" :key="t.id" class="tpl-card" @click="openTemplateForm(t, true)">
          <div class="tpl-card-top">
            <div class="tpl-card-logo">[[ (t.project_name || '?').slice(0, 1).toUpperCase() ]]</div>
            <div class="tpl-card-titlebox">
              <div class="tpl-card-name" :title="t.project_name">[[ t.project_name ]]</div>
              <div class="tpl-card-sub">[[ t.language || '未指定语言' ]]</div>
            </div>
          </div>

          <div class="tpl-card-meta">
            <div class="tpl-meta-row" v-if="t.git_url">
              <span class="tpl-meta-label">Git</span>
              <span class="tpl-meta-val tpl-truncate" :title="t.git_url">[[ t.git_url ]]</span>
            </div>
            <div class="tpl-meta-row" v-if="t.build_docker_image">
              <span class="tpl-meta-label">镜像</span>
              <span class="tpl-meta-val tpl-truncate" :title="t.build_docker_image">[[ t.build_docker_image ]]</span>
            </div>
            <div class="tpl-meta-row" v-if="tplServiceCount(t)">
              <span class="tpl-meta-label">服务</span>
              <span class="tpl-meta-val">[[ tplServiceCount(t) ]] 个目录</span>
            </div>
            <div class="tpl-meta-row tpl-desc" v-if="t.description">
              <span class="tpl-meta-label">描述</span>
              <span class="tpl-meta-val tpl-truncate" :title="t.description">[[ t.description ]]</span>
            </div>
          </div>

          <div class="tpl-card-foot">
            <span class="tpl-card-time" v-if="t.updated_at">更新于 [[ t.updated_at.slice(0, 10) ]]</span>
            <span class="tpl-card-time" v-else>未记录更新</span>
            <div class="tpl-card-actions" @click.stop>
              <el-button link type="primary" size="small" @click="openTemplateForm(t)">编辑</el-button>
              <el-button link type="success" size="small" @click="copyTemplate(t)">复制</el-button>
              <el-button link type="danger" size="small" @click="deleteTemplate(t)">删除</el-button>
            </div>
          </div>
        </div>
        <el-empty v-if="!loadingTemplates && !templates.length" description="暂无流程模板" :image-size="60"></el-empty>
      </div>
    </el-tab-pane>

    <!-- ═══ 凭据 ═══ -->
    <el-tab-pane label="凭据" name="credentials">
      <div class="tpl-toolbar">
        <span class="tpl-toolbar-count">共 <strong>[[ credentials.length ]]</strong> 个凭据</span>
        <el-button type="primary" size="small" @click="openCredForm(null)">+ 新增凭据</el-button>
      </div>
      <div v-loading="loadingCreds" class="cred-grid">
        <div v-for="c in credentials" :key="c.id" class="cred-card" @click="openCredForm(c, true)">
          <div class="tpl-card-top">
            <div class="tpl-card-logo">[[ (c.name || '?').slice(0, 1).toUpperCase() ]]</div>
            <div class="tpl-card-titlebox">
              <div class="tpl-card-name" :title="c.name">[[ c.name ]]</div>
              <div class="tpl-card-sub">[[ c.type === 'ssh_key' ? 'SSH 私钥凭据' : '密码凭据' ]]</div>
            </div>
            <el-tag size="small" effect="plain" :type="c.type === 'ssh_key' ? 'warning' : 'primary'" class="tpl-card-type">[[ c.type === 'ssh_key' ? 'SSH' : '密码' ]]</el-tag>
          </div>
          <div class="tpl-card-meta">
            <div class="tpl-meta-row" v-if="c.username"><span class="tpl-meta-label">用户</span><span class="tpl-meta-val tpl-truncate" :title="c.username">[[ c.username ]]</span></div>
            <div class="tpl-meta-row" v-if="c.url"><span class="tpl-meta-label">地址</span><span class="tpl-meta-val tpl-truncate" :title="c.url">[[ c.url ]]</span></div>
            <div class="tpl-meta-row" v-if="c.description"><span class="tpl-meta-label">描述</span><span class="tpl-meta-val tpl-truncate" :title="c.description">[[ c.description ]]</span></div>
            <div class="tpl-meta-row" v-if="!c.username && !c.url && !c.description"><span class="tpl-meta-val" style="color:#c0c4cc">点击卡片查看详情</span></div>
          </div>
          <div class="tpl-card-foot">
            <span class="tpl-card-time" v-if="c.updated_at">更新于 [[ c.updated_at.slice(0, 10) ]]</span>
            <span class="tpl-card-time" v-else>未记录更新</span>
            <div class="tpl-card-actions" @click.stop>
              <el-button link type="primary" size="small" @click="openCredForm(c)">编辑</el-button>
              <el-button link type="danger" size="small" @click="deleteCred(c)">删除</el-button>
            </div>
          </div>
        </div>
        <el-empty v-if="!loadingCreds && !credentials.length" description="暂无凭据" :image-size="60"></el-empty>
      </div>
    </el-tab-pane>

    <!-- ═══ Dockerfile 模板 ═══ -->
    <el-tab-pane label="Dockerfile" name="dockerfiles">
      <div class="tpl-toolbar">
        <span class="tpl-toolbar-count">共 <strong>[[ dockerfiles.length ]]</strong> 个模板</span>
        <el-button type="primary" size="small" @click="openDockerfileForm(null)">+ 新增模板</el-button>
      </div>
      <div v-loading="loadingDockers" class="cred-grid">
        <div v-for="d in dockerfiles" :key="d.id" class="df-card" @click="openDockerfileForm(d, true)">
          <div class="tpl-card-top">
            <div class="tpl-card-logo">[[ (d.name || '?').slice(0, 1).toUpperCase() ]]</div>
            <div class="tpl-card-titlebox">
              <div class="tpl-card-name" :title="d.name">[[ d.name ]]</div>
              <div class="tpl-card-sub">[[ (d.project_type || '').toUpperCase() || '通用' ]] 模板</div>
            </div>
            <el-tag size="small" effect="plain" :type="d.project_type === 'vue' ? 'success' : 'primary'" class="tpl-card-type">[[ d.project_type || '通用' ]]</el-tag>
          </div>
          <div class="tpl-card-meta">
            <div class="tpl-meta-row" v-if="d.base_image"><span class="tpl-meta-label">镜像</span><span class="tpl-meta-val tpl-truncate" :title="d.base_image">[[ d.base_image ]]</span></div>
            <div class="tpl-meta-row" v-if="d.description"><span class="tpl-meta-label">描述</span><span class="tpl-meta-val tpl-truncate" :title="d.description">[[ d.description ]]</span></div>
            <div class="tpl-meta-row" v-if="!d.base_image && !d.description"><span class="tpl-meta-val" style="color:#c0c4cc">点击卡片查看详情</span></div>
          </div>
          <div class="tpl-card-foot">
            <span class="tpl-card-time" v-if="d.created_at">创建于 [[ d.created_at.slice(0, 10) ]]</span>
            <span class="tpl-card-time" v-else>未记录时间</span>
            <div class="tpl-card-actions" @click.stop>
              <el-button link type="primary" size="small" @click="openDockerfileForm(d)">编辑</el-button>
              <el-button link type="success" size="small" @click="previewDockerfile(d)">预览</el-button>
              <el-button link type="danger" size="small" @click="deleteDockerfile(d)">删除</el-button>
            </div>
          </div>
        </div>
        <el-empty v-if="!loadingDockers && !dockerfiles.length" description="暂无 Dockerfile 模板" :image-size="60"></el-empty>
      </div>
    </el-tab-pane>

  </el-tabs>

  <!-- ═══ 模板编辑弹窗（单页全量展示） ═══ -->
  <el-dialog v-model="tplFormVisible" :title="tplForm.id ? '编辑流程模板' : '新增流程模板'" width="1080px" class="cicd-dialog" :close-on-click-modal="false">
    <el-form label-width="130px" size="small">
      <div class="cicd-section-title">基本信息</div>
      <el-form-item label="项目" required>
        <el-select v-model="tplForm.project_id" placeholder="选择项目" style="width:100%" :disabled="tplReadonly || !!tplForm.id">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="项目类型" required>
        <el-radio-group v-model="tplForm.project_type" @change="onTplTypeChange">
          <el-radio label="backend">后端</el-radio>
          <el-radio label="frontend">前端</el-radio>
        </el-radio-group>
        <span v-if="tplReadonly" style="font-size:12px;color:#909399;margin-left:8px">可切换查看不同类型的配置</span>
      </el-form-item>
      <el-form-item label="语言" required>
        <el-select :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].language" style="width:100%">
          <template v-if="tplForm.project_type==='backend'">
            <el-option label="Java" value="java" /><el-option label="Go" value="go" /><el-option label="Python" value="python" />
          </template>
          <template v-else>
            <el-option label="Vue" value="vue" /><el-option label="React" value="react" />
          </template>
        </el-select>
      </el-form-item>
      <el-form-item label="描述"><el-input :disabled="tplReadonly" v-model="tplForm.description" /></el-form-item>

      <div class="cicd-section-title">Git 配置</div>
      <el-form-item label="Git 地址" required>
        <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].git_url" placeholder="如：git@192.168.1.10:group/project.git 或 https://git.example.com/group/project.git" />
      </el-form-item>
      <el-form-item label="Git Docker镜像" required>
        <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].git_docker_image" placeholder="alpine/git:latest" />
      </el-form-item>
      <el-form-item label="Git 凭据">
        <el-select :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].git_credential_id" clearable placeholder="选择凭据" style="width:100%">
          <el-option v-for="c in credentials" :key="c.id" :label="c.name + ' (' + c.type + ')'" :value="c.id" />
        </el-select>
      </el-form-item>

      <div class="cicd-section-title">编译配置</div>
      <el-form-item label="编译镜像">
        <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].build_docker_image" :placeholder="tplForm.project_type==='backend' ? '如：maven:3.8-jdk-8（留空则在 Agent 宿主机执行）' : '如：node:16（留空则在 Agent 宿主机执行）'" />
      </el-form-item>
      <el-form-item label="编译命令" required>
        <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].build_command" type="textarea" :rows="3" :placeholder="tplForm.project_type==='backend' ? 'mvn clean package -DskipTests' : 'npm install && npm run build'" />
      </el-form-item>

      <div class="cicd-section-title">
        产物配置
        <div class="cicd-section-hint">
          <template v-if="tplForm.project_type==='backend'">每个服务目录对应一个微服务，收集 服务目录/产物目录 到 product 下并并发构建镜像；产物目录支持 | 分隔多候选按序探测、* 通配（如 target/pkg | target/*.jar）</template>
          <template v-else>前端项目固定收集 dist 目录作为产物</template>
        </div>
      </div>
      <template v-if="tplForm.project_type==='backend'">
        <el-form-item label="服务目录">
          <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].artifact_dirs" type="textarea" :rows="12" placeholder="每行一个服务目录（相对代码根目录），如：&#10;ysh-gateway&#10;ysh-modules/ysh-app&#10;留空=编译成功后跳过收集/打镜像，部署步骤等待勾选配置" />
          <div class="cicd-field-hint" style="font-size:12px;color:#909399;line-height:1.6;margin-top:4px">留空则构建在 clone+编译成功后跳过产物收集/打镜像/推送，部署步骤进入等待状态，可在构建面板点「配置服务目录」浏览编译后目录勾选回填到模板，然后重新触发构建。</div>
        </el-form-item>
        <el-form-item label="产物目录">
          <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].artifact_dir" placeholder="产物相对路径，支持 | 多候选与 * 通配，如：target/pkg | target/*.jar" />
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item label-width="0"><el-alert type="success" :closable="false" show-icon title="前端项目固定收集 dist 目录作为产物" /></el-form-item>
      </template>

      <template v-if="tplForm.project_type==='backend'">
        <div class="cicd-section-title">
          镜像构建
          <div class="cicd-section-hint">镜像名自动生成：{Harbor}/{项目}-{环境}/{服务名}:{tag}，无需填写；Harbor 凭据在添加 Agent 时配置</div>
        </div>
        <el-form-item label="Dockerfile模板">
          <el-select :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].dockerfile_template_id" clearable placeholder="选择模板" style="width:100%">
            <el-option v-for="d in dockerfiles" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </template>
    </el-form>

        <template #footer>
      <template v-if="tplReadonly">
        <el-button type="primary" @click="tplReadonly = false">编辑</el-button>
        <el-button @click="tplFormVisible=false">关闭</el-button>
      </template>
      <template v-else>
        <el-button @click="tplFormVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTemplate">保存</el-button>
      </template>
    </template>
  </el-dialog>

  <!-- ═══ 凭据编辑弹窗 ═══ -->
  <el-dialog v-model="credFormVisible" :title="credForm.id ? '编辑凭据' : '新增凭据'" width="460px" class="cicd-dialog" :close-on-click-modal="false">
    <el-form label-width="80px" size="small">
      <el-form-item label="名称" required><el-input :disabled="credReadonly" v-model="credForm.name" /></el-form-item>
      <el-form-item label="类型">
        <el-select :disabled="credReadonly" v-model="credForm.type" style="width:100%">
          <el-option label="账号密码" value="password" /><el-option label="SSH Key" value="ssh_key" />
        </el-select>
      </el-form-item>
      <el-form-item label="用户名" v-if="credForm.type !== 'ssh_key'"><el-input :disabled="credReadonly" v-model="credForm.username" placeholder="root / admin" /></el-form-item>
      <el-form-item :label="credForm.type === 'ssh_key' ? '私钥' : '密码'" :required="!credForm.id">
        <el-input :disabled="credReadonly" v-model="credForm.secret" :type="credForm.type === 'ssh_key' ? 'textarea' : 'password'" :rows="credForm.type === 'ssh_key' ? 8 : 3" :show-password="credForm.type !== 'ssh_key'"
                  :placeholder="credForm.id ? '留空则不修改' : (credForm.type === 'ssh_key' ? '粘贴私钥全文（-----BEGIN ... PRIVATE KEY-----）' : '请输入')" :style="credForm.type==='ssh_key'?'font-family:monospace':''" />
      </el-form-item>
      <el-form-item label="描述"><el-input :disabled="credReadonly" v-model="credForm.description" /></el-form-item>
    </el-form>
    <template #footer>
      <template v-if="credReadonly">
        <el-button type="primary" @click="credReadonly = false">编辑</el-button>
        <el-button @click="credFormVisible=false">关闭</el-button>
      </template>
      <template v-else>
        <el-button @click="credFormVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveCred">保存</el-button>
      </template>
    </template>
  </el-dialog>

  <!-- ═══ Dockerfile 编辑弹窗 ═══ -->
  <el-dialog v-model="dockerFormVisible" :title="dockerForm.id ? '编辑 Dockerfile 模板' : '新增 Dockerfile 模板'" width="640px" class="cicd-dialog" :close-on-click-modal="false">
    <el-form label-width="90px" size="small">
      <el-form-item label="名称" required><el-input :disabled="dfReadonly" v-model="dockerForm.name" /></el-form-item>
      <el-form-item label="项目类型">
        <el-select :disabled="dfReadonly" v-model="dockerForm.project_type" style="width:100%">
          <el-option label="Java" value="java" /><el-option label="Node" value="node" /><el-option label="Go" value="go" />
        </el-select>
      </el-form-item>
      <el-form-item label="基础镜像"><el-input :disabled="dfReadonly" v-model="dockerForm.base_image" /></el-form-item>
      <el-form-item label="模板内容">
        <el-input :disabled="dfReadonly" v-model="dockerForm.content" type="textarea" :rows="10" style="font-family:monospace" placeholder="FROM {{base_image}}&#10;WORKDIR /app&#10;..." />
        <div style="font-size:12px;color:#909399;margin-top:4px;line-height:1.8">
          可用占位符：<code>{{base_image}}</code> <code>{{jar_name}}</code> <code>{{jar_path}}</code> <code>{{workdir}}</code><br>
          <code>{{workdir}}</code> = 服务名称（如 <code>ysh-gateway</code>），WORKDIR 建议使用此占位符
        </div>
      </el-form-item>
      <el-form-item label="描述"><el-input :disabled="dfReadonly" v-model="dockerForm.description" /></el-form-item>
    </el-form>
    <template #footer>
      <template v-if="dfReadonly">
        <el-button type="primary" @click="dfReadonly = false">编辑</el-button>
        <el-button @click="dockerFormVisible=false">关闭</el-button>
      </template>
      <template v-else>
        <el-button @click="dockerFormVisible=false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDockerfile">保存</el-button>
      </template>
    </template>
  </el-dialog>

  <!-- ═══ Dockerfile 预览弹窗 ═══ -->
  <el-dialog v-model="previewVisible" title="Dockerfile 预览" width="600px">
    <pre style="background:#f5f7fa;color:#606266;border:1px solid #ebeef5;padding:12px;border-radius:6px;font-size:12px;overflow:auto;max-height:50vh;font-family:Consolas,Menlo,monospace">[[ previewContent ]]</pre>
  </el-dialog>

</div>
`,

  data() {
    return {
      activeTab: 'templates',
      projects: [],
      saving: false,
      // 模板
      templates: [], loadingTemplates: false,
      tplFormVisible: false, tplForm: {},
      // 凭据
      credentials: [], loadingCreds: false,
      credFormVisible: false, credForm: {},
      tplReadonly: false, credReadonly: false, dfReadonly: false,
      // Dockerfile
      dockerfiles: [], loadingDockers: false,
      dockerFormVisible: false, dockerForm: {},
      previewVisible: false, previewContent: '',
    };
  },

  mounted() {
    this.loadTemplates();
  },

  methods: {
    // ─── 通用 ─────────────────────────────────────────────
    onTabChange(tab) {
      if (tab === 'templates') this.loadTemplates();
      else if (tab === 'credentials') this.loadCredentials();
      else if (tab === 'dockerfiles') this.loadDockerfiles();
    },
    loadProjects() {
      ajax('GET', '/api/admin/projects', null, res => {
        if (res.code === 200) this.projects = res.data || [];
      });
    },

    // ─── 流程模板 ─────────────────────────────────────────
    loadTemplates() {
      this.loadingTemplates = true;
      ajax('GET', '/api/cicd/templates', null, res => {
        this.loadingTemplates = false;
        if (res.code === 200) this.templates = res.data || [];
      });
    },
    tplCfg(key) {
      const cfg = (this.detailData.configs || {})[this.detailData.project_type] || {};
      const v = cfg[key];
      return (v === null || v === undefined || v === '') ? '-' : v;
    },
    // 流程模板卡片：统计服务目录数量（按换行拆分 artifact_dirs）
    tplServiceCount(t) {
      const cfg = (t && t.configs && t.configs[t.project_type]) || {};
      return (cfg.artifact_dirs || '').split('\n').map(s => s.trim()).filter(Boolean).length;
    },
    credName(id) {
      const c = this.credentials.find(x => String(x.id) === String(id));
      return c ? c.name : (id || '-');
    },
    dfName(id) {
      const d = this.dockerfiles.find(x => String(x.id) === String(id));
      return d ? d.name : (id || '-');
    },
    openTemplateForm(row, readonly) {
      this.tplReadonly = !!readonly;
      const ensureLazy = () => {
        if (!this.projects.length) this.loadProjects();
        if (!this.credentials.length) this.loadCredentials();
        if (!this.dockerfiles.length) this.loadDockerfiles();
      };
      if (!row) {
        this.tplForm = { project_id: '', project_type: 'backend', git_docker_image: 'alpine/git:latest', description: '', configs: this.emptyConfigs() };
        ensureLazy();
        this.tplFormVisible = true;
        return;
      }
      // 编辑/查看：列表为精简字段，拉详情全量回填
      ajax('GET', '/api/cicd/templates/' + row.id, null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg || '加载模板失败'); return; }
        const full = res.data;
        const configs = this.normalizeConfigs(full.configs);
        // 需求：弹窗默认以"后端"为起点（用户可手动切换查看前端配置）
        this.tplForm = { ...full, project_type: 'backend', configs: configs };
        ensureLazy();
        this.tplFormVisible = true;
      });
    },
    // 前后端双份配置默认值（切换类型只切展示，数据互不覆盖）
    emptyConfigs() {
      return {
        backend: { language: 'java', git_docker_image: '', git_url: '', git_credential_id: null, build_docker_image: '', build_command: '', artifact_dirs: '', artifact_dir: '', dockerfile_template_id: null },
        frontend: { language: 'vue', git_docker_image: '', git_url: '', git_credential_id: null, build_docker_image: '', build_command: '', artifact_dirs: '', artifact_dir: '', dockerfile_template_id: null },
      };
    },
    normalizeConfigs(cfg) {
      const d = this.emptyConfigs();
      if (cfg && typeof cfg === 'object') {
        d.backend = { ...d.backend, ...(cfg.backend || {}) };
        d.frontend = { ...d.frontend, ...(cfg.frontend || {}) };
      }
      return d;
    },
    // 切换类型：仅切换展示（configs 双份数据都在，不重置不清空）
    onTplTypeChange() { /* 数据存于 configs[project_type]，切换不动任何值 */ },
    copyTemplate(row) {
      // 复制模板：列表为精简字段，拉详情保留完整配置（去掉 id/project_id 作为新增）
      ajax('GET', '/api/cicd/templates/' + row.id, null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg || '加载模板失败'); return; }
        const full = res.data;
        const { id, project_id, project_name, created_at, updated_at, ...rest } = full;
        const configs = this.normalizeConfigs(full.configs);
        // 复制为新建：默认后端（需求：弹窗默认以"后端"为起点）
        this.tplForm = { ...rest, project_id: '', description: '', project_type: 'backend', configs: configs };
        if (!this.projects.length) this.loadProjects();
        if (!this.credentials.length) this.loadCredentials();
        if (!this.dockerfiles.length) this.loadDockerfiles();
        this.tplFormVisible = true;
      });
    },
    saveTemplate() {
      if (!this.tplForm.project_id) { ElementPlus.ElMessage.warning('请选择项目'); return; }
      const cfg = this.tplForm.configs[this.tplForm.project_type];
      if (!cfg.git_url) { ElementPlus.ElMessage.warning('请填写Git地址'); return; }
      // 服务目录允许留空：编译成功后跳过收集/打镜像，部署步骤等待平台勾选回填后重新构建
      this.saving = true;
      const isEdit = !!this.tplForm.id;
      const url = isEdit ? '/api/cicd/templates/' + this.tplForm.id : '/api/cicd/templates';
      const method = isEdit ? 'PUT' : 'POST';
      ajax(method, url, this.tplForm, res => {
        this.saving = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg || '保存成功');
          this.tplFormVisible = false;
          this.loadTemplates();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      });
    },
    deleteTemplate(row) {
      ElementPlus.ElMessageBox.confirm('确认删除该流程模板？', '提示', { type: 'warning' }).then(() => {
        ajax('DELETE', '/api/cicd/templates/' + row.id, null, res => {
          if (res.code === 200) { ElementPlus.ElMessage.success('已删除'); this.loadTemplates(); }
          else ElementPlus.ElMessage.error(res.msg);
        });
      }).catch(() => {});
    },

    // ─── 凭据 ─────────────────────────────────────────────
    loadCredentials() {
      this.loadingCreds = true;
      ajax('GET', '/api/cicd/credentials', null, res => {
        this.loadingCreds = false;
        if (res.code === 200) this.credentials = res.data || [];
      });
    },
    openCredForm(row, readonly) {
      this.credReadonly = !!readonly;
      if (!row) {
        this.credForm = { name: '', type: 'password', username: '', secret: '', description: '' };
        this.credFormVisible = true;
        return;
      }
      // 编辑/详情：拉详情全量回填
      ajax('GET', '/api/cicd/credentials/' + row.id, null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg || '加载凭据失败'); return; }
        this.credForm = { ...res.data, secret: '' };
        this.credFormVisible = true;
      });
    },
    saveCred() {
      if (!this.credForm.name) { ElementPlus.ElMessage.warning('请填写名称'); return; }
      if (!this.credForm.id && !this.credForm.secret) { ElementPlus.ElMessage.warning('请填写密码/密钥'); return; }
      this.saving = true;
      const isEdit = !!this.credForm.id;
      const url = isEdit ? '/api/cicd/credentials/' + this.credForm.id : '/api/cicd/credentials';
      const method = isEdit ? 'PUT' : 'POST';
      ajax(method, url, this.credForm, res => {
        this.saving = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg || '保存成功');
          this.credFormVisible = false;
          this.loadCredentials();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      });
    },
    deleteCred(row) {
      ElementPlus.ElMessageBox.confirm('确认删除凭据「' + row.name + '」？', '提示', { type: 'warning' }).then(() => {
        ajax('DELETE', '/api/cicd/credentials/' + row.id, null, res => {
          if (res.code === 200) { ElementPlus.ElMessage.success('已删除'); this.loadCredentials(); }
          else ElementPlus.ElMessage.error(res.msg);
        });
      }).catch(() => {});
    },
    // ─── Dockerfile ───────────────────────────────────────
    loadDockerfiles() {
      this.loadingDockers = true;
      ajax('GET', '/api/cicd/dockerfiles', null, res => {
        this.loadingDockers = false;
        if (res.code === 200) this.dockerfiles = res.data || [];
      });
    },
    openDockerfileForm(row, readonly) {
      this.dfReadonly = !!readonly;
      if (!row) {
        this.dockerForm = { name: '', project_type: 'java', base_image: '', content: '', description: '', is_builtin: false };
        this.dockerFormVisible = true;
        return;
      }
      // 编辑/详情：拉详情全量回填（含 content）
      ajax('GET', '/api/cicd/dockerfiles/' + row.id, null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg || '加载模板失败'); return; }
        this.dockerForm = { ...res.data };
        this.dockerFormVisible = true;
      });
    },
    saveDockerfile() {
      if (!this.dockerForm.name) { ElementPlus.ElMessage.warning('请填写名称'); return; }
      this.saving = true;
      const isEdit = !!this.dockerForm.id;
      const url = isEdit ? '/api/cicd/dockerfiles/' + this.dockerForm.id : '/api/cicd/dockerfiles';
      const method = isEdit ? 'PUT' : 'POST';
      ajax(method, url, this.dockerForm, res => {
        this.saving = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg || '保存成功');
          this.dockerFormVisible = false;
          this.loadDockerfiles();
        } else {
          ElementPlus.ElMessage.error(res.msg || '保存失败');
        }
      });
    },
    deleteDockerfile(row) {
      ElementPlus.ElMessageBox.confirm('确认删除模板「' + row.name + '」？', '提示', { type: 'warning' }).then(() => {
        ajax('DELETE', '/api/cicd/dockerfiles/' + row.id, null, res => {
          if (res.code === 200) { ElementPlus.ElMessage.success('已删除'); this.loadDockerfiles(); }
          else ElementPlus.ElMessage.error(res.msg);
        });
      }).catch(() => {});
    },
    previewDockerfile(row) {
      ajax('GET', '/api/cicd/dockerfiles/' + row.id + '/preview', null, res => {
        if (res.code === 200) {
          this.previewContent = res.data.content || '';
          this.previewVisible = true;
        }
      });
    },

  }
};
