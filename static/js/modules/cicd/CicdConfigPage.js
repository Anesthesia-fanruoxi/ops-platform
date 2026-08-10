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
      <div style="margin-bottom:10px">
        <el-button type="primary" size="small" @click="openTemplateForm(null)">+ 新增模板</el-button>
      </div>
      <el-table :data="templates" v-loading="loadingTemplates" stripe border size="small"
                :header-cell-style="{background:'#f5f7fa',fontWeight:'bold'}">
        <el-table-column prop="project_name" label="项目" width="130" />
        <el-table-column label="类型" width="80" align="center">
          <template #default="s">
            <el-tag :type="s.row.project_type==='frontend'?'success':''" size="small">[[ s.row.project_type==='frontend'?'前端':'后端' ]]</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="language" label="语言" width="70" align="center" />
        <el-table-column prop="git_docker_image" label="Git镜像" width="150" show-overflow-tooltip />
        <el-table-column prop="git_url" label="Git地址" min-width="200" show-overflow-tooltip />
        <el-table-column prop="build_docker_image" label="编译镜像" width="180" show-overflow-tooltip />
        <el-table-column label="操作" width="160" align="center" fixed="right">
          <template #default="s">
            <el-button link type="primary" size="small" @click="openTemplateForm(s.row)">编辑</el-button>
            <el-button link type="success" size="small" @click="copyTemplate(s.row)">复制</el-button>
            <el-button link type="danger" size="small" @click="deleteTemplate(s.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

    <!-- ═══ 凭据 ═══ -->
    <el-tab-pane label="凭据" name="credentials">
      <div style="margin-bottom:10px">
        <el-button type="primary" size="small" @click="openCredForm(null)">+ 新增凭据</el-button>
      </div>
      <el-table :data="credentials" v-loading="loadingCreds" stripe border size="small"
                :header-cell-style="{background:'#f5f7fa',fontWeight:'bold'}">
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column prop="type" label="类型" width="90" align="center" />
        <el-table-column prop="username" label="用户名" width="130" />
        <el-table-column prop="description" label="描述" min-width="180" show-overflow-tooltip />
        <el-table-column prop="updated_at" label="更新时间" width="150" />
        <el-table-column label="操作" width="160" align="center" fixed="right">
          <template #default="s">
            <el-button link type="primary" size="small" @click="openCredForm(s.row)">编辑</el-button>
            <el-button link type="success" size="small" @click="testCred(s.row)">测试</el-button>
            <el-button link type="danger" size="small" @click="deleteCred(s.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

    <!-- ═══ Dockerfile 模板 ═══ -->
    <el-tab-pane label="Dockerfile" name="dockerfiles">
      <div style="margin-bottom:10px">
        <el-button type="primary" size="small" @click="openDockerfileForm(null)">+ 新增模板</el-button>
      </div>
      <el-table :data="dockerfiles" v-loading="loadingDockers" stripe border size="small"
                :header-cell-style="{background:'#f5f7fa',fontWeight:'bold'}">
        <el-table-column prop="name" label="名称" width="200" />
        <el-table-column prop="project_type" label="类型" width="70" align="center" />
        <el-table-column prop="base_image" label="基础镜像" width="340" show-overflow-tooltip />
        <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
        <el-table-column label="操作" width="160" align="center" fixed="right">
          <template #default="s">
            <el-button link type="primary" size="small" @click="openDockerfileForm(s.row)">编辑</el-button>
            <el-button link type="success" size="small" @click="previewDockerfile(s.row)">预览</el-button>
            <el-button link type="danger" size="small" @click="deleteDockerfile(s.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-tab-pane>

  </el-tabs>

  <!-- ═══ 模板编辑弹窗（单页全量展示） ═══ -->
  <el-dialog v-model="tplFormVisible" :title="tplForm.id ? '编辑流程模板' : '新增流程模板'" width="900px" top="2vh" :close-on-click-modal="false">
    <el-form label-width="120px" size="small">
      <el-divider content-position="left">基本信息</el-divider>
      <el-form-item label="项目" required>
        <el-select v-model="tplForm.project_id" placeholder="选择项目" style="width:100%" :disabled="!!tplForm.id">
          <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="项目类型" required>
        <el-radio-group v-model="tplForm.project_type">
          <el-radio label="backend">后端</el-radio>
          <el-radio label="frontend">前端</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="语言" required>
        <el-select v-model="tplForm.language" style="width:100%">
          <template v-if="tplForm.project_type==='backend'">
            <el-option label="Java" value="java" /><el-option label="Go" value="go" /><el-option label="Python" value="python" />
          </template>
          <template v-else>
            <el-option label="Vue" value="vue" /><el-option label="React" value="react" />
          </template>
        </el-select>
      </el-form-item>
      <el-form-item label="描述"><el-input v-model="tplForm.description" /></el-form-item>

      <el-divider content-position="left">Git 配置</el-divider>
      <el-form-item label="Git Docker镜像" required>
        <el-input v-model="tplForm.git_docker_image" placeholder="alpine/git:latest" />
      </el-form-item>
      <el-form-item label="Git 地址" required>
        <el-input v-model="tplForm.git_url" placeholder="https://gitlab.com/group/project.git" />
      </el-form-item>
      <el-form-item label="Git 凭据">
        <el-select v-model="tplForm.git_credential_id" clearable placeholder="选择凭据" style="width:100%">
          <el-option v-for="c in credentials" :key="c.id" :label="c.name + ' (' + c.type + ')'" :value="c.id" />
        </el-select>
      </el-form-item>

      <el-divider content-position="left">编译配置</el-divider>
      <el-form-item label="编译Docker镜像" required>
        <el-input v-model="tplForm.build_docker_image" :placeholder="tplForm.project_type==='backend' ? 'maven:3.9-eclipse-temurin-17' : 'node:18-alpine'" />
      </el-form-item>
      <el-form-item label="编译命令" required>
        <el-input v-model="tplForm.build_command" type="textarea" :rows="3" :placeholder="tplForm.project_type==='backend' ? 'mvn clean package -DskipTests' : 'npm install && npm run build'" />
      </el-form-item>

      <el-divider content-position="left">
        <div style="display:flex;align-items:center;gap:8px;width:100%">
          <span>产物配置</span>
          <span style="font-size:12px;color:#909399;font-weight:normal">
            <template v-if="tplForm.project_type==='backend'">每个服务目录对应一个微服务，收集 服务目录/产物目录 到 product 下（如 ysh-gateway/pkg）并并发构建镜像</template>
            <template v-else>前端项目固定收集 dist 目录作为产物</template>
          </span>
        </div>
      </el-divider>
      <template v-if="tplForm.project_type==='backend'">
        <el-form-item label="服务目录" required>
          <el-input v-model="tplForm.artifact_dirs" type="textarea" :rows="12" placeholder="每行一个服务目录（相对代码根目录），如：&#10;ysh-gateway&#10;ysh-modules/ysh-app" />
        </el-form-item>
        <el-form-item label="产物目录" required>
          <el-input v-model="tplForm.artifact_dir" placeholder="各服务内统一的产物相对路径，如 target/pkg" />
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item label-width="0"><el-alert type="success" :closable="false" show-icon title="前端项目固定收集 dist 目录作为产物" /></el-form-item>
      </template>

      <template v-if="tplForm.project_type==='backend'">
        <el-divider content-position="left">
          <div style="display:flex;align-items:center;gap:8px;width:100%">
            <span>镜像构建</span>
            <span style="font-size:12px;color:#909399;font-weight:normal">镜像名自动生成：{Harbor}/{项目}-{环境}/{服务名}:{tag}，无需填写；Harbor 凭据在添加 Agent 时配置</span>
          </div>
        </el-divider>
        <el-form-item label="Dockerfile模板">
          <el-select v-model="tplForm.dockerfile_template_id" clearable placeholder="选择模板" style="width:100%">
            <el-option v-for="d in dockerfiles" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </template>
    </el-form>

    <template #footer>
      <el-button @click="tplFormVisible=false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="saveTemplate">保存</el-button>
    </template>
  </el-dialog>

  <!-- ═══ 凭据编辑弹窗 ═══ -->
  <el-dialog v-model="credFormVisible" :title="credForm.id ? '编辑凭据' : '新增凭据'" width="460px" :close-on-click-modal="false">
    <el-form label-width="80px" size="small">
      <el-form-item label="名称" required><el-input v-model="credForm.name" /></el-form-item>
      <el-form-item label="类型">
        <el-select v-model="credForm.type" style="width:100%">
          <el-option label="账号密码" value="password" /><el-option label="SSH Key" value="ssh_key" />
        </el-select>
      </el-form-item>
      <el-form-item label="用户名" v-if="credForm.type !== 'ssh_key'"><el-input v-model="credForm.username" placeholder="root / admin" /></el-form-item>
      <el-form-item :label="credForm.type === 'ssh_key' ? '私钥' : '密码'" :required="!credForm.id">
        <el-input v-model="credForm.secret" :type="credForm.type === 'ssh_key' ? 'textarea' : 'password'" :rows="credForm.type === 'ssh_key' ? 8 : 3" :show-password="credForm.type !== 'ssh_key'"
                  :placeholder="credForm.id ? '留空则不修改' : (credForm.type === 'ssh_key' ? '粘贴私钥全文（-----BEGIN ... PRIVATE KEY-----）' : '请输入')" :style="credForm.type==='ssh_key'?'font-family:monospace':''" />
      </el-form-item>
      <el-form-item label="描述"><el-input v-model="credForm.description" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="credFormVisible=false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="saveCred">保存</el-button>
    </template>
  </el-dialog>

  <!-- ═══ Dockerfile 编辑弹窗 ═══ -->
  <el-dialog v-model="dockerFormVisible" :title="dockerForm.id ? '编辑 Dockerfile 模板' : '新增 Dockerfile 模板'" width="640px" :close-on-click-modal="false">
    <el-form label-width="90px" size="small">
      <el-form-item label="名称" required><el-input v-model="dockerForm.name" /></el-form-item>
      <el-form-item label="项目类型">
        <el-select v-model="dockerForm.project_type" style="width:100%">
          <el-option label="Java" value="java" /><el-option label="Node" value="node" /><el-option label="Go" value="go" />
        </el-select>
      </el-form-item>
      <el-form-item label="基础镜像"><el-input v-model="dockerForm.base_image" /></el-form-item>
      <el-form-item label="模板内容">
        <el-input v-model="dockerForm.content" type="textarea" :rows="10" style="font-family:monospace" placeholder="FROM {{base_image}}&#10;WORKDIR /app&#10;..." />
        <div style="font-size:12px;color:#909399;margin-top:4px;line-height:1.8">
          可用占位符：<code>{{base_image}}</code> <code>{{jar_name}}</code> <code>{{jar_path}}</code> <code>{{workdir}}</code><br>
          <code>{{workdir}}</code> = 服务名称（如 <code>ysh-gateway</code>），WORKDIR 建议使用此占位符
        </div>
      </el-form-item>
      <el-form-item label="描述"><el-input v-model="dockerForm.description" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dockerFormVisible=false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="saveDockerfile">保存</el-button>
    </template>
  </el-dialog>

  <!-- ═══ Dockerfile 预览弹窗 ═══ -->
  <el-dialog v-model="previewVisible" title="Dockerfile 预览" width="600px">
    <pre style="background:#1e1e1e;color:#d4d4d4;padding:12px;border-radius:6px;font-size:12px;overflow:auto;max-height:50vh">[[ previewContent ]]</pre>
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
      // Dockerfile
      dockerfiles: [], loadingDockers: false,
      dockerFormVisible: false, dockerForm: {},
      previewVisible: false, previewContent: '',
    };
  },

  mounted() {
    this.loadProjects();
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
    openTemplateForm(row) {
      if (row) {
        this.tplForm = { ...row };
      } else {
        this.tplForm = { project_id: '', project_type: 'backend', language: 'java', git_docker_image: 'alpine/git:latest', git_url: '', git_credential_id: '', build_docker_image: '', build_command: '', artifact_dirs: '', artifact_dir: '', dockerfile_template_id: '', description: '' };
      }
      // 确保凭据和dockerfile列表已加载
      if (!this.credentials.length) this.loadCredentials();
      if (!this.dockerfiles.length) this.loadDockerfiles();
      this.tplFormVisible = true;
    },
    copyTemplate(row) {
      // 复制模板：预填配置但去掉id和project_id（作为新增）
      const { id, project_id, project_name, created_at, updated_at, ...rest } = row;
      this.tplForm = { ...rest, project_id: '', description: '' };
      if (!this.credentials.length) this.loadCredentials();
      if (!this.dockerfiles.length) this.loadDockerfiles();
      this.tplFormVisible = true;
    },
    saveTemplate() {
      if (!this.tplForm.project_id) { ElementPlus.ElMessage.warning('请选择项目'); return; }
      if (!this.tplForm.git_url) { ElementPlus.ElMessage.warning('请填写Git地址'); return; }
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
    openCredForm(row) {
      this.credForm = row ? { ...row, secret: '' } : { name: '', type: 'password', username: '', secret: '', description: '' };
      this.credFormVisible = true;
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
    testCred(row) {
      ajax('POST', '/api/cicd/credentials/' + row.id + '/test', {}, res => {
        if (res.code === 200) ElementPlus.ElMessage.success(res.data ? res.data.message || '测试通过' : '测试通过');
        else ElementPlus.ElMessage.error(res.msg || '测试失败');
      });
    },

    // ─── Dockerfile ───────────────────────────────────────
    loadDockerfiles() {
      this.loadingDockers = true;
      ajax('GET', '/api/cicd/dockerfiles', null, res => {
        this.loadingDockers = false;
        if (res.code === 200) this.dockerfiles = res.data || [];
      });
    },
    openDockerfileForm(row) {
      this.dockerForm = row ? { ...row } : { name: '', project_type: 'java', base_image: '', content: '', description: '', is_builtin: false };
      this.dockerFormVisible = true;
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
