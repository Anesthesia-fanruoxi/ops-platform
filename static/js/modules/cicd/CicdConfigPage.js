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
            <div class="tpl-meta-row">
              <span class="tpl-meta-label">通知</span>
              <span class="tpl-meta-val" :style="t.notify_enabled ? 'color:#67c23a' : 'color:#c0c4cc'">[[ t.notify_enabled ? '飞书通知已开启' : '未开启' ]]</span>
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

    <!-- ═══ 多仓库模板（独立于单仓流程模板） ═══ -->
    <el-tab-pane label="多仓库模板" name="multi">
      <div class="tpl-toolbar">
        <span class="tpl-toolbar-count">共 <strong>[[ multiTemplates.length ]]</strong> 个多仓库模板</span>
        <el-button type="primary" size="small" @click="openMultiForm(null)">+ 新增多仓库模板</el-button>
      </div>
      <div v-loading="multiLoading" class="cred-grid">
        <div v-for="t in multiTemplates" :key="t.id" class="tpl-card" @click="openMultiForm(t)">
          <div class="tpl-card-top">
            <div class="tpl-card-logo">[[ (t.project_name || '?').slice(0, 1).toUpperCase() ]]</div>
            <div class="tpl-card-titlebox">
              <div class="tpl-card-name" :title="t.project_name">[[ t.project_name ]]</div>
              <div class="tpl-card-sub">[[ t.name || '多仓库模板' ]]</div>
            </div>
            <el-tag v-if="!t.enabled" size="small" type="info" effect="plain">已禁用</el-tag>
          </div>
          <div class="tpl-card-meta">
            <div class="tpl-meta-row"><span class="tpl-meta-label">仓库</span><span class="tpl-meta-val">[[ t.repo_count ]] 个</span></div>
            <div class="tpl-meta-row"><span class="tpl-meta-label">服务</span><span class="tpl-meta-val">[[ t.service_count ]] 个</span></div>
            <div class="tpl-meta-row" v-if="t.maven_settings_name"><span class="tpl-meta-label">Settings</span><span class="tpl-meta-val tpl-truncate" :title="t.maven_settings_name">[[ t.maven_settings_name ]]</span></div>
            <div class="tpl-meta-row" v-if="t.publish_artifacts"><span class="tpl-meta-label">发布</span><span class="tpl-meta-val" style="color:#67c23a">自动上传私仓</span></div>
            <div class="tpl-meta-row tpl-desc" v-if="t.description"><span class="tpl-meta-label">描述</span><span class="tpl-meta-val tpl-truncate">[[ t.description ]]</span></div>
          </div>
          <div class="tpl-card-foot">
            <span class="tpl-card-time">[[ t.updated_at ? '更新于 ' + t.updated_at.slice(0, 10) : '未记录更新' ]]</span>
            <div class="tpl-card-actions" @click.stop>
              <el-button link type="primary" size="small" @click="openMultiForm(t)">编辑</el-button>
              <el-button link type="danger" size="small" @click="deleteMulti(t)">删除</el-button>
            </div>
          </div>
        </div>
        <el-empty v-if="!multiLoading && !multiTemplates.length" description="暂无多仓库模板（单仓项目继续用「流程模板」）" :image-size="60"></el-empty>
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

    <!-- ═══ Maven Settings ═══ -->
    <el-tab-pane label="Maven Settings" name="maven-settings">
      <div class="tpl-toolbar">
        <span class="tpl-toolbar-count">共 <strong>[[ mavenSettings.length ]]</strong> 份 settings.xml</span>
        <el-button type="primary" size="small" @click="openMavenSettingForm(null)">+ 新增 Settings</el-button>
      </div>
      <div v-loading="mavenLoading" class="cred-grid">
        <div v-for="m in mavenSettings" :key="m.id" class="tpl-card" @click="openMavenSettingForm(m)">
          <div class="tpl-card-top">
            <div class="tpl-card-logo">[[ (m.name || '?').slice(0, 1).toUpperCase() ]]</div>
            <div class="tpl-card-titlebox">
              <div class="tpl-card-name" :title="m.name">[[ m.name ]]</div>
              <div class="tpl-card-sub">settings.xml</div>
            </div>
          </div>
          <div class="tpl-card-meta">
            <div class="tpl-meta-row" v-if="m.description"><span class="tpl-meta-label">描述</span><span class="tpl-meta-val tpl-truncate" :title="m.description">[[ m.description ]]</span></div>
            <div class="tpl-meta-row" v-else><span class="tpl-meta-val" style="color:#c0c4cc">点击查看/编辑</span></div>
          </div>
          <div class="tpl-card-foot">
            <span class="tpl-card-time" v-if="m.updated_at">更新于 [[ m.updated_at.slice(0, 10) ]]</span>
            <span class="tpl-card-time" v-else>未记录时间</span>
            <div class="tpl-card-actions" @click.stop>
              <el-button link type="primary" size="small" @click="openMavenSettingForm(m)">编辑</el-button>
              <el-button link type="danger" size="small" @click="deleteMavenSetting(m)">删除</el-button>
            </div>
          </div>
        </div>
        <el-empty v-if="!mavenLoading && !mavenSettings.length" description="暂无 Maven Settings" :image-size="60"></el-empty>
      </div>
    </el-tab-pane>

  </el-tabs>

  <!-- ═══ 模板编辑弹窗（单页全量展示） ═══ -->
  <el-dialog v-model="tplFormVisible" :title="tplForm.id ? '编辑流程模板' : '新增流程模板'" width="1080px" class="cicd-dialog" :close-on-click-modal="false">
    <el-form label-width="130px" size="small">
      <div class="cicd-section-title">基本信息</div>
      <el-form-item label="项目" required>
        <el-select v-model="tplForm.project_id" placeholder="选择项目" style="width:100%" :disabled="tplReadonly || !!tplForm.id"
                   @visible-change="v => v && loadProjects()">
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
        <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].git_docker_image" placeholder="hub.hzbxhd.com/library/git-clone:1.0" />
      </el-form-item>
      <el-form-item label="Git 凭据">
        <el-select :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].git_credential_id" clearable placeholder="选择凭据" style="width:100%">
          <el-option v-for="c in credentials" :key="c.id" :label="c.name + ' (' + c.type + ')'" :value="c.id" />
        </el-select>
      </el-form-item>

      <div class="cicd-section-title">编译配置</div>
      <el-form-item label="编译镜像">
        <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].build_docker_image" :placeholder="tplForm.project_type==='backend' ? '如：hub.hzbxhd.com/library/java17-maven:1.0（Java 8 用 java8-maven:1.0；留空则在宿主机执行）' : '如：node:16（留空则在 Agent 宿主机执行）'" />
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

      <div class="cicd-section-title">
        发版通知
        <div class="cicd-section-hint">开启后，构建/部署结束由平台自动推送飞书卡片。地址留空则使用「系统设置 → 平台设置」中的全局机器人；两处都未配置时通知步骤标记为「跳过」，不影响发版</div>
      </div>
      <el-form-item label="开启通知">
        <el-switch :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].notify_enabled" />
        <span style="font-size:12px;color:#909399;margin-left:8px">关闭时通知步骤标记为「跳过」</span>
      </el-form-item>
      <template v-if="tplForm.configs[tplForm.project_type].notify_enabled">
        <el-form-item label="Webhook 地址">
          <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].notify_webhook_url" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx" />
          <div class="cicd-field-hint" style="font-size:12px;color:#909399;line-height:1.6;margin-top:4px">
            填写后只发到该群；留空则用系统设置里的全局 Webhook（适合「只开启不单独配置」）
          </div>
        </el-form-item>
        <el-form-item label="签名密钥">
          <el-input :disabled="tplReadonly" v-model="tplForm.configs[tplForm.project_type].notify_webhook_secret" type="password" show-password placeholder="机器人开启「签名校验」时填写，未开启可留空" />
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

  <!-- ═══ Maven Settings 编辑弹窗 ═══ -->
  <el-dialog v-model="mavenFormVisible" :title="mavenForm.id ? '编辑 Maven Settings' : '新增 Maven Settings'" width="760px" class="cicd-dialog" :close-on-click-modal="false">
    <el-form label-width="90px" size="small">
      <el-form-item label="名称" required><el-input v-model="mavenForm.name" /></el-form-item>
      <el-form-item label="描述"><el-input v-model="mavenForm.description" /></el-form-item>
      <el-form-item label="release 地址">
        <el-input v-model="mavenForm.release_url" placeholder="http://nexus/repository/maven-releases/" />
      </el-form-item>
      <el-form-item label="snapshot 地址">
        <el-input v-model="mavenForm.snapshot_url" placeholder="http://nexus/repository/maven-snapshots/" />
      </el-form-item>
      <el-form-item label="settings.xml" required>
        <el-input v-model="mavenForm.content" type="textarea" :rows="20" style="font-family:Consolas,Menlo,monospace"
                  placeholder="粘贴 settings.xml 全文（含 mirrors / servers / profiles）" />
        <div style="font-size:12px;color:#909399;line-height:1.7;margin-top:4px">
          内容加密存储；构建时挂到容器的 /root/.m2/settings.xml，构建结束即删除。发布时使用下方两个地址，settings 里需有 nexus-releases / nexus-snapshots 两个 server。
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="mavenFormVisible=false">取消</el-button>
      <el-button type="primary" :loading="mavenSaving" @click="saveMavenSetting">保存</el-button>
    </template>
  </el-dialog>

  <!-- ═══ Dockerfile 预览弹窗 ═══ -->
  <el-dialog v-model="previewVisible" title="Dockerfile 预览" width="600px">
    <pre style="background:#f5f7fa;color:#606266;border:1px solid #ebeef5;padding:12px;border-radius:6px;font-size:12px;overflow:auto;max-height:50vh;font-family:Consolas,Menlo,monospace">[[ previewContent ]]</pre>
  </el-dialog>
  <!-- ═══ 多仓库模板编辑（前四步合并为仓库表格） ═══ -->
  <el-dialog v-model="multiFormVisible" :title="multiForm.id ? '编辑多仓库模板' : '新增多仓库模板'"
             width="85%" top="5vh" class="cicd-dialog multi-dialog" :close-on-click-modal="false">
    <el-form label-width="90px" size="small">
      <div style="display:flex;gap:12px">
        <el-form-item label="项目" required style="flex:1">
          <el-select v-model="multiForm.project_id" placeholder="选择项目" style="width:100%" :disabled="!!multiForm.id"
                     @visible-change="v => v && loadProjects()">
            <el-option v-for="p in projects" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板名" style="flex:1">
          <el-input v-model="multiForm.name" placeholder="默认：{项目} 多仓库模板" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="multiForm.enabled" /></el-form-item>
      </div>
      <el-form-item label="描述"><el-input v-model="multiForm.description" /></el-form-item>
      <el-form-item label="Settings">
        <el-select v-model="multiForm.maven_settings_id" clearable placeholder="不指定（使用 Agent 默认 settings.xml）" style="width:100%">
          <el-option v-for="m in mavenSettings" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
        <div style="font-size:12px;color:#909399;line-height:1.6;margin-top:4px">后端仓库的默认 Maven settings（前端仓库忽略），构建时可再覆盖</div>
      </el-form-item>
      <el-form-item label="发布制品">
        <el-switch v-model="multiForm.publish_artifacts" />
        <span style="font-size:12px;color:#909399;margin-left:8px">后端仓库构建后自动 deploy 到所选 Settings 的 releases/snapshots（前端仓库忽略）；编译命令只写 package，不要再写 deploy</span>
      </el-form-item>
    </el-form>

    <div style="display:flex;align-items:center;justify-content:space-between;margin:4px 0 8px">
      <span style="font-size:13px;color:#606266">仓库构建配置（一个仓库一行：Git → 编译 → 产物 → Dockerfile）</span>
      <span style="display:flex;gap:8px">
        <el-button size="small" type="primary" :disabled="!multiSelection.length" @click="openMultiBuildBatch">构建选中</el-button>
        <el-button size="small" @click="openMultiImport">导入 JSON / Excel</el-button>
        <el-button size="small" @click="exportMultiJson">导出 JSON</el-button>
        <el-button size="small" @click="openMultiDockerfileBulk">按 Java 版本填 Dockerfile</el-button>
        <el-button size="small" @click="addMultiItem">+ 添加仓库</el-button>
      </span>
    </div>
    <el-table :data="multiForm.items" border size="small" style="width:100%" @selection-change="onMultiSelectionChange">
      <el-table-column type="selection" width="42" :selectable="row => !!row.id" />
      <el-table-column label="类型" width="96">
        <template #default="{ row }">
          <el-select v-model="row.project_type" size="small" style="width:100%" @change="onMultiItemTypeChange(row)">
            <el-option label="后端" value="backend" />
            <el-option label="前端" value="frontend" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="Git 地址" min-width="220">
        <template #default="{ row }"><el-input v-model="row.git_url" size="small" placeholder="git@codeup...:group/repo.git" /></template>
      </el-table-column>
      <el-table-column label="Git 镜像" width="150">
        <template #default="{ row }"><el-input v-model="row.git_docker_image" size="small" placeholder="hub.hzbxhd.com/library/git-clone:1.0" /></template>
      </el-table-column>
      <el-table-column label="凭据" width="140">
        <template #default="{ row }">
          <el-select v-model="row.git_credential_id" size="small" clearable placeholder="选择" style="width:100%">
            <el-option v-for="c in credentials" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </template>
      </el-table-column>
      <el-table-column label="编译镜像" width="170">
        <template #default="{ row }"><el-input v-model="row.build_docker_image" size="small" :placeholder="row.project_type === 'frontend' ? '如 node:18（留空用宿主机）' : 'hub.hzbxhd.com/library/java17-maven:1.0（留空用宿主机）'" /></template>
      </el-table-column>
      <el-table-column label="编译命令" min-width="200">
        <template #default="{ row }"><el-input v-model="row.build_command" size="small" :placeholder="row.project_type === 'frontend' ? 'npm install && npm run build' : 'mvn -B -DskipTests clean package'" /></template>
      </el-table-column>
      <el-table-column label="Dockerfile" width="150">
        <template #default="{ row }">
          <el-select v-if="row.project_type !== 'frontend'" v-model="row.dockerfile_template_id" size="small" clearable :disabled="!!row.artifact_only" placeholder="选择" style="width:100%">
            <el-option v-for="d in dockerfiles" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <span v-else style="color:#c0c4cc;font-size:12px">不适用</span>
        </template>
      </el-table-column>
      <el-table-column label="仅制品" width="130" align="center">
        <template #default="{ row }">
          <template v-if="row.project_type !== 'frontend'">
            <el-checkbox v-model="row.artifact_only" />
            <el-input v-if="row.artifact_only" v-model="row.git_branch" size="small" placeholder="分支 如 main" style="margin-top:2px" />
          </template>
          <span v-else style="color:#c0c4cc;font-size:12px">不适用</span>
        </template>
      </el-table-column>
      <el-table-column label="发布目录" width="170">
        <template #default="{ row }">
          <el-input v-if="row.project_type === 'frontend'" v-model="row.publish_dir" size="small"
                    :placeholder="row.repo_name || '默认仓库名'" />
          <span v-else style="color:#c0c4cc;font-size:12px">—</span>
        </template>
      </el-table-column>
      <el-table-column label="服务" width="80" align="center">
        <template #default="{ row }">
          <span v-if="row.project_type === 'frontend'" style="color:#c0c4cc;font-size:12px">dist</span>
          <span v-else-if="row.artifact_only" style="color:#909399;font-size:12px">不产服务</span>
          <el-button v-else link type="primary" size="small" @click="openMultiServices(row)">
            [[ (row.services || []).length ]] 个
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="110" align="center">
        <template #default="{ row, $index }">
          <el-button link type="success" size="small" @click="openMultiBuild(row)">构建</el-button>
          <el-button link type="danger" size="small" @click="removeMultiItem($index)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="font-size:12px;color:#909399;line-height:1.7;margin-top:8px">
      仓库名自动取 Git 地址最后一段（去掉 .git）。仓库默认在根目录编译；服务产物目录相对仓库根目录，精确包名由「服务」里的 jar 名决定，Agent 只收集该文件。服务可先不配：不配时按仓库名出一个镜像。服务名即镜像名与 YAML 文件名。<br>
      勾选「仅制品」表示该仓库只编译并把 jar 发布到私仓（如 ruoyi-common），不打镜像、不部署：批次会自动带上它并排在最前，其他仓库等它发布完成后再开始构建；分支留空则跟随批次统一分支。<br>
      前端仓库固定收集 dist，发布到 <code>{Agent 前端挂载根}/{项目}/{环境}/{发布目录}</code>，发布目录留空默认仓库名；多个前端仓库请使用不同发布目录，避免互相覆盖。
    </div>

    <template #footer>
      <el-button @click="multiFormVisible=false">取消</el-button>
      <el-button type="primary" :loading="multiSaving" @click="saveMulti">保存</el-button>
    </template>
  </el-dialog>

  <!-- 多仓库：服务映射（批量粘贴） -->
  <el-dialog v-model="multiSvcVisible" :title="'服务配置 - ' + multiSvcRepo" width="720px" :close-on-click-modal="false">
    <div style="font-size:12px;color:#606266;margin-bottom:8px">
      每行：<code>服务名|产物目录|jar名（精确包名，留空自动识别）|jvm(8/17，可选)</code>；产物在当前仓库根目录写 <code>.</code>
    </div>
    <el-input v-model="multiSvcText" type="textarea" :rows="14" style="font-family:Consolas,Menlo,monospace"
              placeholder="lq-user|ruoyi-modules/lq-user|lq-user.jar|8&#10;bank-company-conn|.|bank-company-connection.jar|17" />
    <template #footer>
      <el-button @click="multiSvcVisible=false">取消</el-button>
      <el-button type="primary" @click="applyMultiServices">应用</el-button>
    </template>
  </el-dialog>
  <!-- 多仓库：批量导入 -->
  <el-dialog v-model="multiImportVisible" title="批量导入仓库与服务" width="720px" :close-on-click-modal="false">
    <el-radio-group v-model="multiImportMode" size="small" style="margin-bottom:10px">
      <el-radio-button label="json">JSON</el-radio-button>
      <el-radio-button label="excel">Excel / CSV 粘贴</el-radio-button>
    </el-radio-group>
    <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:10px">
      <el-select v-model="multiImportCredential" size="small" clearable placeholder="统一 Git 凭据（可选）" style="width:200px">
        <el-option v-for="c in credentials" :key="c.id" :label="c.name" :value="c.id" />
      </el-select>
      <el-select v-model="multiImportDockerfile8" size="small" clearable placeholder="Java 8 Dockerfile 模板（可选）" style="width:220px">
        <el-option v-for="d in dockerfiles" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <el-select v-model="multiImportDockerfile17" size="small" clearable placeholder="Java 17 Dockerfile 模板（可选）" style="width:220px">
        <el-option v-for="d in dockerfiles" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <span style="font-size:12px;color:#909399">按服务 jvm 自动填入对应行，导入后仍可逐行调整</span>
    </div>

    <template v-if="multiImportMode === 'json'">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
        <input type="file" accept=".json,application/json" @change="onMultiImportFile" />
        <span style="font-size:12px;color:#909399">选择 .json 文件，或直接把内容贴到下面</span>
      </div>
      <el-input v-model="multiImportText" type="textarea" :rows="16"
                style="font-family:Consolas,Menlo,monospace"
                placeholder='{"repos":[{"git_url":"git@...","git_docker_image":"hub.hzbxhd.com/library/git-clone:1.0","build_docker_image":"hub.hzbxhd.com/library/java17-maven:1.0","build_command":"mvn -B -DskipTests clean package","services":[{"service_name":"lq-user","artifact_dir":"ruoyi-modules/lq-user","jar_name":"lq-user.jar","jvm":"8"}]}]}' />
      <div style="font-size:12px;color:#909399;line-height:1.8;margin-top:6px">
        仓库名可不填，自动取 Git 地址最后一段（去掉 .git）；凭据用上方统一选择，Dockerfile 按 Java 8 / Java 17 两个下拉分别选，导入时按服务 jvm 自动填入对应行。JSON 不需要带凭据/Dockerfile。
        兼容字段别名 services[].name→service_name、services[].dir→artifact_dir；旧 JSON 的 git_credential_name / dockerfile_template_name 仍兼容。<br>
        示例文件：项目目录下 <code>config/multi-repo-template.verified.json</code>（19 仓 / 44 服务）。
      </div>
    </template>

    <template v-else>
      <div style="font-size:12px;color:#606266;line-height:1.8;margin-bottom:6px">
        从 Excel 复制整块粘贴（制表符/逗号分隔）。首行表头：<br>
        <code>Git地址	Git镜像	编译镜像	编译命令	服务名	服务产物目录	jar名	jvm	Dockerfile模板</code><br>
        同一仓库写多行，Git 地址只在第一行填即可，后续行留空会自动合并。
      </div>
      <el-input v-model="multiImportText" type="textarea" :rows="14"
                style="font-family:Consolas,Menlo,monospace"
                placeholder="git@codeup...:group/backend-api.git	hub.hzbxhd.com/library/git-clone:1.0	hub.hzbxhd.com/library/java8-maven:1.0	mvn -B -DskipTests clean package	lq-user	ruoyi-modules/lq-user	lq-user.jar	8	jdk8-jar" />
    </template>

    <template #footer>
      <el-button @click="multiImportVisible=false">取消</el-button>
      <el-button type="primary" @click="applyMultiImport">导入并填充</el-button>
    </template>
  </el-dialog>

  <!-- 多仓库：按 Java 版本批量填 Dockerfile -->
  <el-dialog v-model="multiDfBulkVisible" title="按 Java 版本填 Dockerfile" width="480px" :close-on-click-modal="false">
    <div style="font-size:12px;color:#606266;line-height:1.7;margin-bottom:10px">
      按各仓库服务的 jvm（8/17）匹配；未识别到版本的仓库不处理，会覆盖这些行已选的 Dockerfile。
    </div>
    <el-form label-width="130px" size="small">
      <el-form-item label="Java 8 模板">
        <el-select v-model="multiDfBulk8" clearable placeholder="不设置" style="width:100%">
          <el-option v-for="d in dockerfiles" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="Java 17 模板">
        <el-select v-model="multiDfBulk17" clearable placeholder="不设置" style="width:100%">
          <el-option v-for="d in dockerfiles" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="multiDfBulkVisible=false">取消</el-button>
      <el-button type="primary" @click="applyMultiDockerfileBulk">应用</el-button>
    </template>
  </el-dialog>

  <!-- 多仓库：单仓构建（选环境 + 分支） -->
  <el-dialog v-model="multiBuildVisible" :title="'构建 - ' + multiBuildRepo" width="520px" :close-on-click-modal="false">
    <el-form label-width="70px" size="small">
      <el-form-item label="环境" required>
        <el-select v-model="multiBuildEnv" placeholder="选择环境" style="width:100%">
          <el-option v-for="e in multiBuildEnvs" :key="e.id" :label="e.name" :value="e.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="分支">
        <el-select v-model="multiBuildBranch" filterable allow-create default-first-option
                   placeholder="选择或输入分支" style="width:100%">
          <el-option v-for="b in multiBuildBranches" :key="b" :label="b" :value="b" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="multiBuildHasBackend" label="Settings">
        <el-select v-model="multiBuildSettings" clearable placeholder="默认（模板配置）" style="width:100%">
          <el-option v-for="m in mavenSettings" :key="m.id" :label="m.name" :value="m.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <div v-if="multiBuildItems.length > 1" style="font-size:12px;color:#409eff;line-height:1.7">
      已选 [[ multiBuildItems.length ]] 个仓库，统一使用第一个仓库「[[ multiBuildFirstRepo ]]」的分支；修改分支会应用到全部选中仓库。
    </div>
    <div v-else style="font-size:12px;color:#909399;line-height:1.7">
      单个仓库构建，选择该仓库自己的分支；前端仓库构建后发布到各自 Web 目录，后端构建目录、镜像命名空间与单仓项目一致（{项目}-{环境}）。
    </div>
    <div v-if="multiBuildPrereqHint" style="font-size:12px;color:#e6a23c;line-height:1.7">[[ multiBuildPrereqHint ]]</div>
    <template #footer>
      <el-button @click="multiBuildVisible=false">取消</el-button>
      <el-button type="primary" :loading="multiBuilding" @click="submitMultiBuild">开始构建</el-button>
    </template>
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
      // 多仓库模板
      multiTemplates: [], multiLoading: false,
      multiFormVisible: false, multiForm: { items: [] }, multiSaving: false,
      multiSvcVisible: false, multiSvcIndex: -1, multiSvcRepo: '', multiSvcText: '',
      multiBuildVisible: false, multiBuildItem: null, multiBuildItems: [], multiBuildRepo: '', multiBuildFirstRepo: '', multiBuildEnvs: [],
      multiBuildEnv: '', multiBuildBranches: [], multiBuildBranch: 'master', multiBuilding: false,
      multiBuildSettings: null, multiSelection: [], multiBuildPrereqHint: '', multiBuildHasBackend: false,
      multiImportVisible: false, multiImportMode: 'json', multiImportText: '', multiImportCredential: null,
      multiImportDockerfile8: null, multiImportDockerfile17: null,
      multiDfBulkVisible: false, multiDfBulk8: null, multiDfBulk17: null,
      mavenSettings: [], mavenLoading: false, mavenFormVisible: false, mavenForm: {}, mavenSaving: false,
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
      else if (tab === 'maven-settings') this.loadMavenSettings();
      else if (tab === 'multi') {
        this.loadProjects();
        this.loadCredentials();
        this.loadDockerfiles();
        this.loadMavenSettings();
        this.loadMultiTemplates();
      }
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
        // 每次都刷新：项目/凭据/Dockerfile 可能在别的页面刚新增，不能只按“空才加载”
        this.loadProjects();
        this.loadCredentials();
        this.loadDockerfiles();
      };
      if (!row) {
        this.tplForm = { project_id: '', project_type: 'backend', git_docker_image: 'hub.hzbxhd.com/library/git-clone:1.0', description: '', configs: this.emptyConfigs() };
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
        backend: { language: 'java', git_docker_image: '', git_url: '', git_credential_id: null, build_docker_image: '', build_command: '', artifact_dirs: '', artifact_dir: '', dockerfile_template_id: null, notify_enabled: false, notify_webhook_url: '', notify_webhook_secret: '' },
        frontend: { language: 'vue', git_docker_image: '', git_url: '', git_credential_id: null, build_docker_image: '', build_command: '', artifact_dirs: '', artifact_dir: '', dockerfile_template_id: null, notify_enabled: false, notify_webhook_url: '', notify_webhook_secret: '' },
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
    // ─── Maven Settings ───────────────────────────────────
    loadMavenSettings() {
      this.mavenLoading = true;
      ajax('GET', '/api/cicd/maven-settings', null, res => {
        this.mavenLoading = false;
        if (res.code === 200) this.mavenSettings = res.data || [];
      }, () => { this.mavenLoading = false; });
    },
    openMavenSettingForm(row) {
      if (!row) {
        this.mavenForm = { name: '', description: '', content: '', release_url: '', snapshot_url: '' };
        this.mavenFormVisible = true;
        return;
      }
      ajax('GET', '/api/cicd/maven-settings/' + row.id, null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg || '加载失败'); return; }
        this.mavenForm = { ...res.data };
        this.mavenFormVisible = true;
      });
    },
    saveMavenSetting() {
      if (!this.mavenForm.name) { ElementPlus.ElMessage.warning('请填写名称'); return; }
      if (!(this.mavenForm.content || '').trim()) { ElementPlus.ElMessage.warning('请填写 settings.xml 内容'); return; }
      this.mavenSaving = true;
      const isEdit = !!this.mavenForm.id;
      ajax(isEdit ? 'PUT' : 'POST', isEdit ? '/api/cicd/maven-settings/' + this.mavenForm.id : '/api/cicd/maven-settings',
        this.mavenForm, res => {
          this.mavenSaving = false;
          if (res.code === 200) {
            ElementPlus.ElMessage.success(res.msg || '保存成功');
            this.mavenFormVisible = false;
            this.loadMavenSettings();
          } else ElementPlus.ElMessage.error(res.msg || '保存失败');
        }, () => { this.mavenSaving = false; });
    },
    deleteMavenSetting(row) {
      ElementPlus.ElMessageBox.confirm('确认删除 Maven Settings「' + row.name + '」？', '提示', { type: 'warning' }).then(() => {
        ajax('DELETE', '/api/cicd/maven-settings/' + row.id, null, res => {
          if (res.code === 200) { ElementPlus.ElMessage.success('已删除'); this.loadMavenSettings(); }
          else ElementPlus.ElMessage.error(res.msg);
        });
      }).catch(() => {});
    },

    // ─── 多仓库模板 ───────────────────────────────────────
    loadMultiTemplates() {
      this.multiLoading = true;
      ajax('GET', '/api/cicd/multi-templates', null, res => {
        this.multiLoading = false;
        if (res.code === 200) this.multiTemplates = res.data || [];
      }, () => { this.multiLoading = false; });
    },
    _repoNameFromUrl(url) {
      const s = String(url || '').trim().replace(/\/+$/, '');
      if (!s) return '';
      const tail = s.split(/[/:]/).filter(Boolean).pop() || '';
      return tail.replace(/\.git$/i, '');
    },
    _repoJvm(row) {
      const set = new Set((row.services || []).map(s => String(s.jvm || '').trim()).filter(Boolean));
      if (set.size === 1) return Array.from(set)[0];
      const img = String(row.build_docker_image || '').toLowerCase();
      if (/java8|jdk8|jdk-8/.test(img)) return '8';
      if (/java17|jdk17|jdk-17/.test(img)) return '17';
      return '';
    },
    _blankMultiItem(type) {
      const isFe = type === 'frontend';
      return {
        repo_name: '', project_type: isFe ? 'frontend' : 'backend', publish_dir: '',
        git_url: '', git_credential_id: null,
        git_docker_image: 'hub.hzbxhd.com/library/git-clone:1.0',
        build_docker_image: isFe ? '' : 'hub.hzbxhd.com/library/java17-maven:1.0',
        build_command: isFe ? 'npm install && npm run build' : 'mvn -B -DskipTests clean package',
        dockerfile_template_id: null, description: '', enabled: true, services: [],
        artifact_only: false, git_branch: '',
      };
    },
    onMultiItemTypeChange(row) {
      if (row.project_type === 'frontend') {
        row.artifact_only = false;
        row.dockerfile_template_id = null;
        row.services = [];
        if (!row.build_docker_image || /java(8|17)-maven/i.test(row.build_docker_image)) row.build_docker_image = '';
        if (!row.build_command || /^mvn\b/.test((row.build_command || '').trim())) row.build_command = 'npm install && npm run build';
        if (!row.publish_dir) row.publish_dir = row.repo_name || this._repoNameFromUrl(row.git_url);
      } else {
        if (!row.build_command || /^npm\b/.test((row.build_command || '').trim())) row.build_command = this._defaultBuildCommand('backend');
        if (!row.build_docker_image) row.build_docker_image = 'hub.hzbxhd.com/library/java17-maven:1.0';
      }
    },
    openMultiForm(t) {
      // 项目/凭据/Dockerfile/Settings 可能是刚在别的页面新增的，打开时统一刷新
      this.loadProjects();
      this.loadCredentials();
      this.loadDockerfiles();
      this.loadMavenSettings();
      if (!t) {
        this.multiForm = { project_id: '', name: '', description: '', enabled: true,
                           maven_settings_id: null, publish_artifacts: false,
                           items: [this._blankMultiItem()] };
        this.multiFormVisible = true;
        return;
      }
      ajax('GET', '/api/cicd/multi-templates/' + t.id, null, res => {
        if (res.code !== 200) { ElementPlus.ElMessage.error(res.msg || '加载失败'); return; }
        const d = res.data;
        d.items = (d.items || []).map(it => ({
          ...it,
          repo_name: it.repo_name || this._repoNameFromUrl(it.git_url),
          project_type: it.project_type === 'frontend' ? 'frontend' : 'backend',
          publish_dir: it.publish_dir || '',
          git_docker_image: it.git_docker_image || 'hub.hzbxhd.com/library/git-clone:1.0',
          build_docker_image: it.build_docker_image || '',
          services: it.services || [],
          artifact_only: !!it.artifact_only,
          git_branch: it.git_branch || '',
        }));
        this.multiForm = d;
        this.multiFormVisible = true;
      });
    },
    addMultiItem() { this.multiForm.items.push(this._blankMultiItem()); },
    removeMultiItem(i) { this.multiForm.items.splice(i, 1); },
    openMultiServices(row) {
      this.multiSvcIndex = this.multiForm.items.indexOf(row);
      this.multiSvcRepo = row.repo_name || this._repoNameFromUrl(row.git_url) || ('仓库#' + (this.multiSvcIndex + 1));
      this.multiSvcText = (row.services || []).map(s =>
        [s.service_name, s.artifact_dir || '.', s.jar_name || '', s.jvm || ''].join('|').replace(/\|+$/, '')
      ).join('\n');
      this.multiSvcVisible = true;
    },
    applyMultiServices() {
      const lines = (this.multiSvcText || '').split('\n').map(l => l.trim()).filter(Boolean);
      const services = [];
      for (const line of lines) {
        const p = line.split('|').map(s => s.trim());
        if (!p[0]) continue;
        services.push({ service_name: p[0], artifact_dir: p[1] || '.', jar_name: p[2] || '', jvm: p[3] || '' });
      }
      const row = this.multiForm.items[this.multiSvcIndex];
      if (row) row.services = services;
      this.multiSvcVisible = false;
    },
    saveMulti() {
      const f = this.multiForm;
      if (!f.project_id) { ElementPlus.ElMessage.warning('请选择项目'); return; }
      if (!(f.items || []).length) { ElementPlus.ElMessage.warning('请至少配置一个仓库'); return; }
      const hasBackend = (f.items || []).some(it => (it.project_type || 'backend') === 'backend');
      if (f.publish_artifacts && hasBackend) {
        if (!f.maven_settings_id) { ElementPlus.ElMessage.warning('开启发布制品请选择 Maven Settings'); return; }
        const ms = this.mavenSettings.find(m => String(m.id) === String(f.maven_settings_id));
        if (ms && (!ms.release_url || !ms.snapshot_url)) {
          ElementPlus.ElMessage.warning('所选 Maven Settings 未配置 release / snapshot 发布地址');
          return;
        }
      }
      const seenPublish = new Set();
      for (let i = 0; i < f.items.length; i++) {
        const it = f.items[i];
        if (!it.git_url) { ElementPlus.ElMessage.warning('第 ' + (i + 1) + ' 行缺 Git 地址'); return; }
        it.repo_name = this._repoNameFromUrl(it.git_url);
        if (!it.repo_name) { ElementPlus.ElMessage.warning('第 ' + (i + 1) + ' 行无法从 Git 地址识别仓库名'); return; }
        if (!it.git_docker_image) it.git_docker_image = 'hub.hzbxhd.com/library/git-clone:1.0';
        if (it.project_type === 'frontend') {
          it.artifact_only = false;
          it.dockerfile_template_id = null;
          it.services = [];
          it.publish_dir = (it.publish_dir || it.repo_name).trim();
          if (!it.publish_dir || it.publish_dir.startsWith('/') || it.publish_dir.includes('..')) {
            ElementPlus.ElMessage.warning('仓库「' + it.repo_name + '」发布目录不合法（相对路径，不能以 / 开头或包含 ..）');
            return;
          }
          if (seenPublish.has(it.publish_dir)) {
            ElementPlus.ElMessage.warning('发布目录重复：' + it.publish_dir + '，多个前端请使用不同子目录');
            return;
          }
          seenPublish.add(it.publish_dir);
        } else {
          if (!it.build_docker_image) it.build_docker_image = 'hub.hzbxhd.com/library/java17-maven:1.0';
        }
        if (!it.build_command) { ElementPlus.ElMessage.warning('仓库「' + it.repo_name + '」缺编译命令'); return; }
      }
      this.multiSaving = true;
      const isEdit = !!f.id;
      ajax(isEdit ? 'PUT' : 'POST', isEdit ? '/api/cicd/multi-templates/' + f.id : '/api/cicd/multi-templates',
        f, res => {
          this.multiSaving = false;
          if (res.code === 200) {
            ElementPlus.ElMessage.success(res.msg || '保存成功');
            this.multiFormVisible = false;
            this.loadMultiTemplates();
          } else ElementPlus.ElMessage.error(res.msg || '保存失败');
        }, () => { this.multiSaving = false; });
    },
    deleteMulti(t) {
      ElementPlus.ElMessageBox.confirm('确认删除项目「' + t.project_name + '」的多仓库模板？', '提示', { type: 'warning' })
        .then(() => {
          ajax('DELETE', '/api/cicd/multi-templates/' + t.id, null, res => {
            if (res.code === 200) { ElementPlus.ElMessage.success('已删除'); this.loadMultiTemplates(); }
            else ElementPlus.ElMessage.error(res.msg);
          });
        }).catch(() => {});
    },
    openMultiImport() {
      // 导入时要按名称解析凭据/Dockerfile，先确保列表是最新的
      this.loadCredentials();
      this.loadDockerfiles();
      this.multiImportMode = 'json';
      this.multiImportText = '';
      this.multiImportCredential = null;
      this.multiImportDockerfile8 = null;
      this.multiImportDockerfile17 = null;
      this.multiImportVisible = true;
    },
    onMultiImportFile(e) {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => { this.multiImportText = String(reader.result || ''); };
      reader.readAsText(f, 'utf-8');
      e.target.value = '';
    },
    openMultiDockerfileBulk() {
      this.loadDockerfiles();
      this.multiDfBulkVisible = true;
    },
    applyMultiDockerfileBulk() {
      if (!this.multiDfBulk8 && !this.multiDfBulk17) {
        ElementPlus.ElMessage.warning('请至少选择 Java 8 或 Java 17 的 Dockerfile 模板');
        return;
      }
      let n = 0;
      for (const it of this.multiForm.items || []) {
        const jvm = this._repoJvm(it);
        if (jvm === '8' && this.multiDfBulk8) {
          it.dockerfile_template_id = this.multiDfBulk8; n++;
        } else if (jvm === '17' && this.multiDfBulk17) {
          it.dockerfile_template_id = this.multiDfBulk17; n++;
        }
      }
      this.multiDfBulkVisible = false;
      if (n) ElementPlus.ElMessage.success('已为 ' + n + ' 个仓库填入 Dockerfile 模板');
      else ElementPlus.ElMessage.warning('没有识别到可匹配 Java 8/17 的仓库');
    },
    _resolveId(list, v) {
      if (v === null || v === undefined || v === '') return null;
      const s = String(v);
      const byId = list.find(x => String(x.id) === s);
      if (byId) return byId.id;
      const byName = list.find(x => x.name === s);
      return byName ? byName.id : null;
    },
    _defaultBuildCommand(type) {
      return type === 'frontend' ? 'npm install && npm run build' : 'mvn -B -DskipTests clean package';
    },
    _normImportedRepo(r) {
      const gitUrl = (r.git_url || '').trim();
      const isFe = r.project_type === 'frontend';
      const repo = {
        id: r.id || undefined,
        repo_name: this._repoNameFromUrl(gitUrl) || (r.repo_name || r.name || '').trim(),
        project_type: isFe ? 'frontend' : 'backend',
        publish_dir: (r.publish_dir || '').trim(),
        git_url: gitUrl,
        git_credential_id: this._resolveId(this.credentials, r.git_credential_id || r.git_credential_name),
        git_docker_image: (r.git_docker_image || 'hub.hzbxhd.com/library/git-clone:1.0').trim(),
        build_docker_image: (r.build_docker_image || (isFe ? '' : 'hub.hzbxhd.com/library/java17-maven:1.0')).trim(),
        build_command: (r.build_command || '').trim(),
        dockerfile_template_id: isFe ? null : this._resolveId(this.dockerfiles, r.dockerfile_template_id || r.dockerfile_template_name),
        enabled: r.enabled !== false,
        artifact_only: isFe ? false : !!r.artifact_only,
        git_branch: (r.git_branch || '').trim(),
        services: isFe ? [] : (r.services || []).map(s => ({
          service_name: (s.service_name || s.name || '').trim(),
          artifact_dir: (s.artifact_dir || s.dir || '.').trim() || '.',
          jar_name: (s.jar_name || s.jar || '').trim(),
          jvm: String(s.jvm || '').trim(),
        })).filter(s => s.service_name),
      };
      if (!repo.build_command) repo.build_command = this._defaultBuildCommand(repo.project_type);
      if (isFe && !repo.publish_dir) repo.publish_dir = repo.repo_name;
      return repo;
    },
    _parseJsonImport(text) {
      const data = JSON.parse(text);
      const repos = Array.isArray(data) ? data : (data.repos || []);
      if (!Array.isArray(repos)) throw new Error('JSON 里没有 repos 数组');
      return repos.map(r => this._normImportedRepo(r));
    },
    _parseTableImport(text) {
      const lines = text.split(/\r?\n/).filter(l => l.trim());
      if (!lines.length) return [];
      const delim = lines[0].includes('\t') ? '\t' : ',';
      const split = l => l.split(delim).map(s => s.trim());
      const head = split(lines[0]);
      const skipHead = head.some(h => /git地址|git镜像|编译镜像|仓库|服务名/i.test(h));
      const rows = skipHead ? lines.slice(1) : lines;
      const map = new Map();
      let last = null;
      for (const line of rows) {
        const c = split(line);
        const get = i => (c[i] || '').trim();
        const gitUrl = get(0);
        if (gitUrl) {
          if (!map.has(gitUrl)) {
            map.set(gitUrl, this._normImportedRepo({ git_url: gitUrl }));
          }
          last = map.get(gitUrl);
        }
        if (!last) continue;
        if (get(1)) last.git_docker_image = get(1);
        if (get(2)) last.build_docker_image = get(2);
        if (get(3)) last.build_command = get(3);
        if (get(4)) {
          last.services.push({
            service_name: get(4),
            artifact_dir: get(5) || '.',
            jar_name: get(6) || '',
            jvm: get(7) || '',
          });
        }
        if (get(8)) last.dockerfile_template_id = this._resolveId(this.dockerfiles, get(8));
      }
      return Array.from(map.values());
    },
    applyMultiImport() {
      const text = (this.multiImportText || '').trim();
      if (!text) { ElementPlus.ElMessage.warning('请粘贴内容或选择 JSON 文件'); return; }
      let items = [];
      try {
        items = this.multiImportMode === 'json' ? this._parseJsonImport(text) : this._parseTableImport(text);
      } catch (e) {
        ElementPlus.ElMessage.error('解析失败：' + (e.message || e));
        return;
      }
      if (!items.length) { ElementPlus.ElMessage.warning('没有解析到仓库'); return; }
      if (this.multiImportCredential) {
        items.forEach(it => { if (!it.git_credential_id) it.git_credential_id = this.multiImportCredential; });
      }
      if (this.multiImportDockerfile8 || this.multiImportDockerfile17) {
        items.forEach(it => {
          if (it.dockerfile_template_id) return;
          const jvm = this._repoJvm(it);
          if (jvm === '8' && this.multiImportDockerfile8) it.dockerfile_template_id = this.multiImportDockerfile8;
          else if (jvm === '17' && this.multiImportDockerfile17) it.dockerfile_template_id = this.multiImportDockerfile17;
        });
      }
      const bad = items.find(it => !it.git_url || !it.repo_name);
      if (bad) {
        ElementPlus.ElMessage.warning('有仓库缺 Git 地址或无法识别仓库名：' + (bad.git_url || '(空)'));
        return;
      }
      const merged = new Map();
      for (const it of items) {
        const key = it.git_url;
        if (!merged.has(key)) {
          merged.set(key, it);
        } else {
          const base = merged.get(key);
          base.services = (base.services || []).concat(it.services || []);
        }
      }
      this.multiForm.items = Array.from(merged.values());
      this.multiImportVisible = false;
      const svcCount = this.multiForm.items.reduce((n, it) => n + (it.services || []).length, 0);
      ElementPlus.ElMessage.success('已导入 ' + this.multiForm.items.length + ' 个仓库 / ' + svcCount + ' 个服务');
    },
    exportMultiJson() {
      const data = {
        repos: (this.multiForm.items || []).map(it => ({
          git_url: it.git_url,
          project_type: it.project_type || 'backend',
          publish_dir: it.publish_dir || '',
          git_docker_image: it.git_docker_image || 'hub.hzbxhd.com/library/git-clone:1.0',
          build_docker_image: it.build_docker_image || '',
          build_command: it.build_command,
          artifact_only: !!it.artifact_only,
          git_branch: it.git_branch || '',
          services: (it.services || []).map(s => ({
            service_name: s.service_name, artifact_dir: s.artifact_dir, jar_name: s.jar_name, jvm: s.jvm,
          })),
        })),
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = (this.multiForm.name || 'multi-repo-template') + '.json';
      a.click();
      URL.revokeObjectURL(a.href);
    },
    onMultiSelectionChange(rows) {
      this.multiSelection = rows || [];
    },
    openMultiBuild(row) {
      if (!row || !row.id) { ElementPlus.ElMessage.warning('请先保存模板，再构建'); return; }
      this._openMultiBuild([row]);
    },
    openMultiBuildBatch() {
      const rows = (this.multiSelection || []).filter(r => r.id);
      if (!rows.length) { ElementPlus.ElMessage.warning('请先勾选要构建的仓库'); return; }
      this._openMultiBuild(rows);
    },
    _openMultiBuild(rows) {
      const list = (rows || []).filter(r => r.id);
      if (!list.length) return;
      this.multiBuildItems = list;
      this.multiBuildItem = list[0];
      this.multiBuildFirstRepo = list[0].repo_name || '';
      this.multiBuildRepo = list.length > 1 ? (list.length + ' 个仓库') : this.multiBuildFirstRepo;
      this.multiBuildHasBackend = list.some(r => (r.project_type || 'backend') === 'backend');
      const prereq = this.multiBuildHasBackend
        ? (this.multiForm.items || []).filter(it => it.artifact_only && it.id && !list.some(r => r.id === it.id))
        : [];
      this.multiBuildPrereqHint = prereq.length
        ? '仅制品仓库会自动并入本批次并优先发布（其他仓库等它完成）：' + prereq.map(it => it.repo_name).join('、')
        : '';
      this.multiBuildEnv = '';
      this.multiBuildBranch = 'master';
      this.multiBuildSettings = this.multiBuildHasBackend ? (this.multiForm.maven_settings_id || null) : null;
      this.multiBuildEnvs = [];
      this.multiBuildBranches = [];
      this.loadMavenSettings();
      const pid = this.multiForm.project_id;
      if (pid) {
        ajax('GET', '/api/admin/projects/' + pid + '/environments', null, res => {
          if (res.code === 200) this.multiBuildEnvs = res.data || [];
        });
      }
      // 分支只取第一个仓库：多仓库时作为统一分支，单仓库时作为该仓库分支
      ajax('GET', '/api/cicd/multi-templates/items/' + list[0].id + '/branches', null, res => {
        if (res.code === 200) this.multiBuildBranches = res.data || [];
      }, () => { /* 拉不到分支时允许手输 */ });
      this.multiBuildVisible = true;
    },
    submitMultiBuild() {
      if (!this.multiBuildEnv) { ElementPlus.ElMessage.warning('请选择环境'); return; }
      if (!this.multiBuildBranch) { ElementPlus.ElMessage.warning('请选择分支'); return; }
      const items = (this.multiBuildItems || []).filter(r => r.id);
      if (!items.length) { ElementPlus.ElMessage.warning('请先选择仓库'); return; }
      this.multiBuilding = true;
      if (items.length > 1) {
        if (!this.multiForm.id) { this.multiBuilding = false; ElementPlus.ElMessage.warning('请先保存模板'); return; }
        ajax('POST', '/api/cicd/multi-templates/' + this.multiForm.id + '/build-batch', {
          environment_id: this.multiBuildEnv,
          item_ids: items.map(r => r.id),
          branch: this.multiBuildBranch,
          maven_settings_id: this.multiBuildSettings || null,
        }, res => {
          this.multiBuilding = false;
          if (res.code === 200) {
            ElementPlus.ElMessage.success(res.msg || ('已触发 ' + ((res.data && res.data.count) || items.length) + ' 个仓库构建'));
            this.multiBuildVisible = false;
          } else ElementPlus.ElMessage.error(res.msg || '触发失败');
        }, () => { this.multiBuilding = false; });
        return;
      }
      ajax('POST', '/api/cicd/multi-templates/items/' + items[0].id + '/build', {
        environment_id: this.multiBuildEnv,
        branch: this.multiBuildBranch,
        maven_settings_id: this.multiBuildSettings || null,
      }, res => {
        this.multiBuilding = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success('构建已触发：' + (res.data.build_no || ''));
          this.multiBuildVisible = false;
        } else ElementPlus.ElMessage.error(res.msg || '触发失败');
      }, () => { this.multiBuilding = false; });
    },

  }
};
