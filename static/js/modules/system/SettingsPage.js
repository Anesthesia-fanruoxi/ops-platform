// 设置分组 → 表单字段默认值（对应后端 ?type=deploy|nginx|middleware）
const SETTING_FORM_MAP = {
  deploy: {
    yaml_output_dir: '', yaml_recycle_dir: '',
    nfs_server: '', nfs_cluster_server: '', nfs_ssh_port: '', nfs_ssh_user: '', nfs_ssh_pass: '',
    nfs_logs_mount: '/data/logs', nfs_data_mount: '/data/project', nfs_datastorg_mount: '/data/project/datastorg',
    harbor_url: '', harbor_user: '', harbor_pass: '',
    harbor_cleanup_keep_versions: '3', harbor_cleanup_cron: '0 0 * * * *',
    k8s_master_ip: '', k8s_cluster_ip: '', k8s_ssh_user: 'root', k8s_ssh_pass: '',
    k8s_kubeconfig: '', k8s_api_server: '',
    k8s_yaml_remote_dir: '/data/yaml', k8s_yaml_remote_recycle_dir: '/data/yaml-recycle',
    default_domain: '', default_nacos_namespace: '',
    default_publicurl: '', default_privateurl: '', default_publicbucket: '', default_privatebucket: '',
    default_ossak: '', default_osssk: '', default_encrypted: '', default_riskKey: '', default_es_pass: '',
    ignored_projects: ''
  },
  nginx: {
    nginx_server: '', nginx_ssh_port: '22', nginx_ssh_user: 'root', nginx_ssh_pass: '',
    nginx_remote_dir: '/etc/nginx/conf.d', nginx_local_dir: './nginx_configs'
  },
  middleware: {
    mysql_default_user: 'root', mysql_default_pass: '',
    redis_user: '', redis_pass: '',
    rabbitmq_user: 'admin', rabbitmq_pass: '',
    nacos_user: 'nacos', nacos_pass: ''
  },
  platform: {
    token_expire_hours: '8',
    password_min_length: '6',
    password_require_upper: '0',
    password_require_digit: '0',
    agent_comm_secret: '',
    authplatform_base_url: '',
    authplatform_platform_id: '',
    authplatform_secret: ''
  }
};

// 密码字段：前端始终不显示真实值，留空表示不修改
const SETTING_PASSWORD_KEYS = [
  'nfs_ssh_pass', 'harbor_pass', 'k8s_ssh_pass', 'k8s_kubeconfig', 'nginx_ssh_pass',
  'authplatform_secret'
];
// 中间件密码：回显显示（可在设置页查看/复制）
const SETTING_REVEAL_KEYS = ['mysql_default_pass', 'redis_pass', 'rabbitmq_pass', 'nacos_pass'];

const SettingsPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card settings-page">
      <div class="settings-tabs">
        <button v-for="tab in tabs" :key="tab.key" type="button"
                :class="['settings-tab', { active: activeTab === tab.key }]"
                @click="activeTab = tab.key">[[ tab.icon ]] [[ tab.label ]]</button>
      </div>

      <!-- 内容滚动区：标题与标签固定，仅此区域滚动 -->
      <div class="settings-body">
      <!-- ── 部署环境 ── -->
      <div v-show="activeTab === 'deploy'">
        <div class="subsection-title">目录配置</div>
        <div class="form-row">
          <div class="form-group w-url">
            <label class="form-label">YAML生成目录</label>
            <input class="form-input" v-model="form.yaml_output_dir" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">YAML回收目录</label>
            <input class="form-input" v-model="form.yaml_recycle_dir" @input="detectChange">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group w-url">
            <label class="form-label">NFS日志挂载目录</label>
            <input class="form-input" v-model="form.nfs_logs_mount" placeholder="/data/logs" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">NFS数据挂载目录</label>
            <input class="form-input" v-model="form.nfs_data_mount" placeholder="/data/project" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">NFS存储挂载目录</label>
            <input class="form-input" v-model="form.nfs_datastorg_mount" placeholder="/data/project/datastorg" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title" style="display:flex;align-items:center;gap:12px">NFS服务器配置
          <button class="btn btn-default btn-sm" @click="testSSH">🔍 测试SSH</button>
          <span class="test-hint">保存后测试</span>
          <span :class="['test-result', sshTestResult.type]">[[ sshTestResult.text ]]</span>
        </div>
        <div class="form-row">
          <div class="form-group w-ip">
            <label class="form-label">NFS服务器地址</label>
            <input class="form-input" v-model="form.nfs_server" @input="detectChange">
            <small style="color:#888">SSH访问用</small>
          </div>
          <div class="form-group w-ip">
            <label class="form-label">NFS集群内网地址</label>
            <input class="form-input" v-model="form.nfs_cluster_server" @input="detectChange">
            <small style="color:#888">YAML中Pod挂载用</small>
          </div>
          <div class="form-group w-port">
            <label class="form-label">SSH端口</label>
            <input class="form-input" v-model="form.nfs_ssh_port" @input="detectChange">
          </div>
          <div class="form-group w-user">
            <label class="form-label">SSH用户名</label>
            <input class="form-input" v-model="form.nfs_ssh_user" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">SSH密码</label>
            <input class="form-input" type="password" v-model="form.nfs_ssh_pass" placeholder="留空则不修改" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title" style="display:flex;align-items:center;gap:12px">Harbor配置
          <button class="btn btn-default btn-sm" @click="testHarbor">🔍 测试Harbor</button>
          <span class="test-hint">保存后测试</span>
          <span :class="['test-result', harborTestResult.type]">[[ harborTestResult.text ]]</span>
        </div>
        <div class="form-row">
          <div class="form-group w-url">
            <label class="form-label">Harbor地址（域名）</label>
            <input class="form-input" v-model="form.harbor_url" placeholder="如: hub.hzbxhd.com（无需 https://）" @input="detectChange">
          </div>
          <div class="form-group w-user">
            <label class="form-label">Harbor用户名</label>
            <input class="form-input" v-model="form.harbor_user" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">Harbor密码</label>
            <input class="form-input" type="password" v-model="form.harbor_pass" placeholder="留空则不修改" @input="detectChange">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group w-port">
            <label class="form-label">镜像保留版本数</label>
            <input class="form-input" type="number" min="1" v-model="form.harbor_cleanup_keep_versions" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">清理调度 Cron</label>
            <input class="form-input" v-model="form.harbor_cleanup_cron" placeholder="0 0 * * * *" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title" style="display:flex;align-items:center;gap:12px">K8s Master配置
          <button class="btn btn-default btn-sm" @click="testK8sSSH">🔍 测试SSH</button>
          <span class="test-hint">保存后测试</span>
          <span :class="['test-result', k8sTestResult.type]">[[ k8sTestResult.text ]]</span>
        </div>
        <div class="form-row">
          <div class="form-group w-ip">
            <label class="form-label">Master 地址 (NodeIP)</label>
            <input class="form-input" v-model="form.k8s_master_ip" placeholder="如: 192.168.3.10" @input="detectChange">
            <small style="color:#888">SSH访问用</small>
          </div>
          <div class="form-group w-ip">
            <label class="form-label">K8s集群内网地址</label>
            <input class="form-input" v-model="form.k8s_cluster_ip" placeholder="如: 172.16.0.10" @input="detectChange">
            <small style="color:#888">Nginx反代/Pod访问用</small>
          </div>
          <div class="form-group w-user">
            <label class="form-label">SSH用户名</label>
            <input class="form-input" v-model="form.k8s_ssh_user" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">SSH密码</label>
            <input class="form-input" type="password" v-model="form.k8s_ssh_pass" placeholder="留空则不修改" @input="detectChange">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group w-url">
            <label class="form-label">远程YAML目录</label>
            <input class="form-input" v-model="form.k8s_yaml_remote_dir" placeholder="如: /data/yaml" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">远程YAML回收目录</label>
            <input class="form-input" v-model="form.k8s_yaml_remote_recycle_dir" placeholder="如: /data/yaml-recycle" @input="detectChange">
          </div>
        </div>

        <div class="form-row">
          <div class="form-group w-url" style="width:100%">
            <label class="form-label">K8s API Server（可选覆盖）</label>
            <input class="form-input" v-model="form.k8s_api_server" placeholder="如: https://172.16.0.10:6443（留空则用 admin.conf 里的 server）" @input="detectChange">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group" style="width:100%">
            <label class="form-label">K8s admin.conf
              <span v-if="form.k8s_kubeconfig_configured" style="color:#67c23a;font-size:12px;margin-left:6px">✓ 已配置</span>
              <span v-else style="color:#e6a23c;font-size:12px;margin-left:6px">未配置</span>
            </label>
            <textarea class="form-input" rows="8" v-model="form.k8s_kubeconfig"
                      placeholder="粘贴 admin.conf 完整内容（含证书，服务信息页查看 Pod 状态/日志用）。留空不修改，粘贴新内容保存即覆盖。" @input="detectChange"
                      style="font-family:monospace;font-size:12px;line-height:1.5"></textarea>
          </div>
        </div>

        <div class="subsection-title">默认配置</div>
        <div class="form-row">
          <div class="form-group w-key">
            <label class="form-label">域名后缀</label>
            <input class="form-input" v-model="form.default_domain" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">默认 Nacos 命名空间 ID</label>
            <input class="form-input" v-model="form.default_nacos_namespace" placeholder="新建项目时自动填充" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title">OSS配置</div>
        <div class="form-row">
          <div class="form-group w-url">
            <label class="form-label">PublicURL</label>
            <input class="form-input" v-model="form.default_publicurl" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">PrivateURL</label>
            <input class="form-input" v-model="form.default_privateurl" @input="detectChange">
          </div>
          <div class="form-group w-key">
            <label class="form-label">Public Bucket</label>
            <input class="form-input" v-model="form.default_publicbucket" @input="detectChange">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group w-key">
            <label class="form-label">Private Bucket</label>
            <input class="form-input" v-model="form.default_privatebucket" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">Access Key</label>
            <input class="form-input" v-model="form.default_ossak" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">Secret Key</label>
            <input class="form-input" v-model="form.default_osssk" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title">密钥配置</div>
        <div class="form-row">
          <div class="form-group w-key">
            <label class="form-label">加密盐</label>
            <input class="form-input" v-model="form.default_encrypted" @input="detectChange">
          </div>
          <div class="form-group w-key">
            <label class="form-label">风控加密盐</label>
            <input class="form-input" v-model="form.default_riskKey" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">ES密码</label>
            <input class="form-input" v-model="form.default_es_pass" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title">项目忽略管理</div>
        <div class="form-row">
          <div class="form-group w-full">
            <label class="form-label">忽略的项目（英文逗号分隔，填写后前端不显示、同步不处理）</label>
            <textarea class="form-input" v-model="form.ignored_projects" rows="3" placeholder="如: telemarketing,business,distribution-system" style="resize:vertical;font-family:monospace" @input="detectChange"></textarea>
          </div>
        </div>
      </div>

      <!-- ── Nginx配置 ── -->
      <div v-show="activeTab === 'nginx'">
        <div class="subsection-title" style="display:flex;align-items:center;gap:12px">Nginx服务器配置
          <button class="btn btn-default btn-sm" @click="testNginxSSH">🔍 测试SSH</button>
          <span class="test-hint">保存后测试</span>
          <span :class="['test-result', nginxTestResult.type]">[[ nginxTestResult.text ]]</span>
        </div>
        <div class="form-row">
          <div class="form-group w-ip">
            <label class="form-label">服务器地址</label>
            <input class="form-input" v-model="form.nginx_server" placeholder="Nginx服务器IP" @input="detectChange">
          </div>
          <div class="form-group w-port">
            <label class="form-label">SSH端口</label>
            <input class="form-input" v-model="form.nginx_ssh_port" @input="detectChange">
          </div>
          <div class="form-group w-user">
            <label class="form-label">SSH用户名</label>
            <input class="form-input" v-model="form.nginx_ssh_user" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">SSH密码</label>
            <input class="form-input" type="password" v-model="form.nginx_ssh_pass" placeholder="留空则不修改" @input="detectChange">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group w-url">
            <label class="form-label">远程配置目录</label>
            <input class="form-input" v-model="form.nginx_remote_dir" placeholder="如: /etc/nginx/conf.d" @input="detectChange">
          </div>
          <div class="form-group w-url">
            <label class="form-label">本地存储目录</label>
            <input class="form-input" v-model="form.nginx_local_dir" placeholder="如: ./nginx_configs" @input="detectChange">
          </div>
        </div>
      </div>

      <!-- ── 中间件配置 ── -->
      <div v-show="activeTab === 'middleware'">
        <div style="margin-bottom:12px;display:flex;align-items:center;gap:8px">
          <span style="font-size:13px;color:#606266">密码明文显示</span>
          <el-switch v-model="showMwPass" size="small" />
          <span style="color:#909399;font-size:12px">开启后中间件密码以明文显示，便于查看/复制</span>
        </div>
        <div class="subsection-title">MySQL（测试环境通用）</div>
        <div class="form-row">
          <div class="form-group w-user">
            <label class="form-label">用户名</label>
            <input class="form-input" v-model="form.mysql_default_user" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">密码</label>
            <input class="form-input" :type="showMwPass ? 'text' : 'password'" v-model="form.mysql_default_pass" placeholder="已保存的密码会显示，留空则不修改" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title">Redis</div>
        <div class="form-row">
          <div class="form-group w-user">
            <label class="form-label">用户名（非必填）</label>
            <input class="form-input" v-model="form.redis_user" placeholder="无则留空" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">密码</label>
            <input class="form-input" :type="showMwPass ? 'text' : 'password'" v-model="form.redis_pass" placeholder="已保存的密码会显示，留空则不修改" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title">RabbitMQ</div>
        <div class="form-row">
          <div class="form-group w-user">
            <label class="form-label">账号</label>
            <input class="form-input" v-model="form.rabbitmq_user" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">密码</label>
            <input class="form-input" :type="showMwPass ? 'text' : 'password'" v-model="form.rabbitmq_pass" placeholder="已保存的密码会显示，留空则不修改" @input="detectChange">
          </div>
        </div>

        <div class="subsection-title">Nacos</div>
        <div class="form-row">
          <div class="form-group w-user">
            <label class="form-label">账号</label>
            <input class="form-input" v-model="form.nacos_user" @input="detectChange">
          </div>
          <div class="form-group w-pass">
            <label class="form-label">密码</label>
            <input class="form-input" :type="showMwPass ? 'text' : 'password'" v-model="form.nacos_pass" placeholder="已保存的密码会显示，留空则不修改" @input="detectChange">
          </div>
        </div>
      </div>

      <!-- ── 平台设置 ── -->
      <div v-show="activeTab === 'platform'">
        <div class="subsection-title">认证</div>
        <div class="form-row">
          <div class="form-group w-port">
            <label class="form-label">Token过期时间（小时）</label>
            <input class="form-input" type="number" min="1" v-model="form.token_expire_hours" @input="detectChange">
            <small style="color:#888">每次有效请求自动续期</small>
          </div>
        </div>

        <div class="subsection-title">密码规则</div>
        <div class="form-row">
          <div class="form-group w-port">
            <label class="form-label">密码最小长度</label>
            <input class="form-input" type="number" min="1" v-model="form.password_min_length" @input="detectChange">
          </div>
          <div class="form-group w-key">
            <label class="form-label">必须包含大写字母</label>
            <select class="form-input" v-model="form.password_require_upper" @input="detectChange">
              <option value="0">否</option>
              <option value="1">是</option>
            </select>
          </div>
          <div class="form-group w-key">
            <label class="form-label">必须包含数字</label>
            <select class="form-input" v-model="form.password_require_digit" @input="detectChange">
              <option value="0">否</option>
              <option value="1">是</option>
            </select>
          </div>
        </div>

        <div class="subsection-title">Agent 通讯密钥</div>
        <div class="form-row">
          <div class="form-group w-full">
            <label class="form-label">Agent 共享密钥（只读，改动会导致所有 Agent 通讯失效）</label>
            <input class="form-input" v-model="form.agent_comm_secret" readonly>
          </div>
        </div>

        <div class="subsection-title">统一鉴权中心（authPlatform）</div>
        <div class="form-row">
          <div class="form-group w-url">
            <label class="form-label">鉴权中心地址</label>
            <input class="form-input" v-model="form.authplatform_base_url" @input="detectChange" placeholder="如 http://127.0.0.1:8080，留空=使用本地账号登录">
          </div>
          <div class="form-group w-key">
            <label class="form-label">平台标识 platform_id</label>
            <input class="form-input" v-model="form.authplatform_platform_id" @input="detectChange" placeholder="如 ops-platform，在鉴权中心后台注册">
          </div>
        </div>
        <div class="form-row">
          <div class="form-group w-full">
            <label class="form-label">平台加密盐 secret（留空表示不修改；保存后不再显示明文）</label>
            <input class="form-input" type="password" v-model="form.authplatform_secret" @input="detectChange" placeholder="注册平台时下发，仅创建时展示一次">
          </div>
        </div>
      </div>

      </div>
      <!-- 底部操作栏：固定显示，不随内容滚动 -->
      <div class="settings-footer">
        <button class="btn btn-primary" :disabled="!hasChanges" @click="saveSettings">💾 保存设置</button>
        <button class="btn btn-default" @click="loadSettings" style="margin-left:10px">🔄 重新加载</button>
      </div>
    </div>
  `,
  data() {
    return {
      activeTab: 'platform',
      form: {}, showMwPass: false,
      originalForm: {},
      hasChanges: false,
      sshTestResult: { text: '', type: '' },
      harborTestResult: { text: '', type: '' },
      k8sTestResult: { text: '', type: '' },
      nginxTestResult: { text: '', type: '' }
    };
  },
  computed: {
    // 标签顺序：平台设置第一位（默认进入），其余按业务分组
    tabs() {
      return [
        { key: 'platform', label: '平台设置', icon: '⚙️' },
        { key: 'deploy', label: '部署环境', icon: '🚀' },
        { key: 'nginx', label: 'Nginx配置', icon: '🌐' },
        { key: 'middleware', label: '中间件配置', icon: '📦' }
      ];
    }
  },
  methods: {
    loadSettings() {
      // 四个标签页分别请求：?type=deploy / nginx / middleware / platform
      const self = this;
      const groups = this.tabs.map(t => t.key);
      let pending = groups.length;
      groups.forEach((group) => {
        ajax('GET', '/api/settings/list?type=' + group, null, (r) => {
          const data = r.data || {};
          const map = SETTING_FORM_MAP[group] || {};
          for (const key in map) {
            if (SETTING_PASSWORD_KEYS.includes(key)) {
              self.form[key] = '';  // 密码不展示，留空表示不修改
              self.form[key + '_configured'] = !!(data[key] && data[key].has_value);
            } else {
              self.form[key] = (data[key] && data[key].value !== undefined) ? data[key].value : map[key];
            }
          }
          pending -= 1;
          if (pending === 0) {
            self.originalForm = JSON.parse(JSON.stringify(self.form));
            self.hasChanges = false;
          }
        });
      });
    },
    detectChange() {
      this.hasChanges = JSON.stringify(this.form) !== JSON.stringify(this.originalForm);
    },
    saveSettings() {
      const data = {};
      for (const key in this.form) {
        const val = this.form[key];
        if (SETTING_PASSWORD_KEYS.includes(key)) {
          if (val && val !== '******') data[key] = val;
        } else if (val !== this.originalForm[key]) {
          data[key] = val;
        }
      }
      if (Object.keys(data).length === 0) {
        showWarning('没有修改任何内容');
        return;
      }
      ajax('POST', '/api/settings/update', data, (r) => {
        if (r.code === 200) {
          showSuccess('设置已保存');
          this.loadSettings();
        } else {
          showError(r.msg || '保存失败');
        }
      });
    },
    testSSH() {
      this.sshTestResult = { text: '测试中...', type: 'testing' };
      ajax('POST', '/api/settings/test-ssh', {}, (r) => {
        this.sshTestResult = r.code === 200
          ? { text: '✅ ' + r.msg, type: 'success' }
          : { text: '❌ ' + r.msg, type: 'error' };
      });
    },
    testHarbor() {
      this.harborTestResult = { text: '测试中...', type: 'testing' };
      ajax('POST', '/api/settings/test-harbor', {}, (r) => {
        const ver = r.data?.harbor_version || '?';
        this.harborTestResult = r.code === 200
          ? { text: '✅ ' + r.msg + ' (' + ver + ')', type: 'success' }
          : { text: '❌ ' + r.msg, type: 'error' };
      });
    },
    testK8sSSH() {
      this.k8sTestResult = { text: '测试中...', type: 'testing' };
      ajax('POST', '/api/settings/test-k8s-ssh', {}, (r) => {
        this.k8sTestResult = r.code === 200
          ? { text: '✅ ' + r.msg, type: 'success' }
          : { text: '❌ ' + r.msg, type: 'error' };
      });
    },
    testNginxSSH() {
      this.nginxTestResult = { text: '测试中...', type: 'testing' };
      ajax('POST', '/api/settings/test-nginx-ssh', {}, (r) => {
        this.nginxTestResult = r.code === 200
          ? { text: '✅ ' + r.msg, type: 'success' }
          : { text: '❌ ' + r.msg, type: 'error' };
      });
    }
  },
  created() {
    this.loadSettings();
  }
};
