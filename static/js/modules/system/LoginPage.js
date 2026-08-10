// 登录页组件：用户登录（统一鉴权）/ 管理员登录（本地密码，仅平台设置）
const LoginPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="login-wrapper">
      <div class="login-card">
        <div class="login-title">运维平台</div>

        <div class="login-tabs">
          <button class="login-tab" :class="{active: activeTab==='user'}" @click="switchTab('user')">用户登录</button>
          <button class="login-tab" :class="{active: activeTab==='admin'}" @click="switchTab('admin')">管理员登录</button>
        </div>

        <!-- 用户登录：统一账号（authPlatform 校验，未接入时本地账号） -->
        <div v-if="activeTab==='user'">
          <div class="login-subtitle">统一账号登录</div>
          <el-form :model="form" :rules="rules" ref="formRef" label-position="top">
            <el-form-item label="用户名" prop="username">
              <el-input v-model="form.username" placeholder="请输入用户名"
                prefix-icon="User" @keyup.enter="handleLogin"></el-input>
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="form.password" type="password" placeholder="请输入密码"
                prefix-icon="Lock" show-password @keyup.enter="handleLogin"></el-input>
            </el-form-item>
            <el-form-item>
              <button class="login-btn" :disabled="loading" @click.prevent="handleLogin">
                [[ loading ? '登录中...' : '登 录' ]]
              </button>
            </el-form-item>
          </el-form>
        </div>

        <!-- 管理员登录：超级管理员（本地账号），仅用于平台设置 -->
        <div v-else>
          <div class="login-subtitle">超级管理员本地登录（仅平台设置）</div>
          <el-form :model="adminForm" :rules="adminRules" ref="adminFormRef" label-position="top">
            <el-form-item label="超级管理员账号" prop="username">
              <el-input v-model="adminForm.username" placeholder="请输入超级管理员账号"
                prefix-icon="User" @keyup.enter="handleAdminLogin"></el-input>
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input v-model="adminForm.password" type="password" placeholder="请输入超级管理员密码"
                prefix-icon="Lock" show-password @keyup.enter="handleAdminLogin"></el-input>
            </el-form-item>
            <el-form-item>
              <button class="login-btn" :disabled="loading" @click.prevent="handleAdminLogin">
                [[ loading ? '登录中...' : '管理员登录' ]]
              </button>
            </el-form-item>
          </el-form>
        </div>

        <div class="login-footer"></div>
      </div>
    </div>
  `,
  setup() {
    const formRef = Vue.ref(null);
    const adminFormRef = Vue.ref(null);
    const form = Vue.reactive({ username: '', password: '' });
    const adminForm = Vue.reactive({ username: '', password: '' });
    const loading = Vue.ref(false);
    const activeTab = Vue.ref('user');

    const rules = {
      username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
      password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
    };
    const adminRules = {
      username: [{ required: true, message: '请输入超级管理员账号', trigger: 'blur' }],
      password: [{ required: true, message: '请输入管理员密码', trigger: 'blur' }],
    };

    function switchTab(tab) {
      activeTab.value = tab;
      loading.value = false;
    }

    // 登录成功后的统一处理：保存 token、更新全局状态、按角色跳转
    function onLoginSuccess(res) {
      localStorage.setItem('auth_token', res.data.token);
      localStorage.setItem('auth_expires', res.data.expires_at);

      authState.isLoggedIn = true;
      authState.username = res.data.user.username;
      authState.nickname = res.data.user.nickname || '';
      authState.roleName = res.data.user.role_name || '';
      authState.permissions = res.data.user.permissions || [];
      authState.isSuperAdmin = !!res.data.user.is_super_admin;

      // 超级管理员只进设置页，普通用户进部署平台
      router.push(authState.isSuperAdmin ? '/settings' : '/create/project');
    }

    const handleLogin = async () => {
      if (!formRef.value) return;
      try {
        await formRef.value.validate();
      } catch (e) {
        return;
      }

      loading.value = true;
      ajax('POST', '/api/auth/login', {
        username: form.username,
        password: form.password,
      }, (res) => {
        loading.value = false;
        if (res.code === 200) {
          onLoginSuccess(res);
        } else {
          ElementPlus.ElMessage.error(res.msg || '登录失败');
        }
      });
    };

    const handleAdminLogin = async () => {
      if (!adminFormRef.value) return;
      try {
        await adminFormRef.value.validate();
      } catch (e) {
        return;
      }

      loading.value = true;
      ajax('POST', '/api/auth/admin-login', {
        username: adminForm.username,
        password: adminForm.password,
      }, (res) => {
        loading.value = false;
        if (res.code === 200) {
          onLoginSuccess(res);
        } else {
          ElementPlus.ElMessage.error(res.msg || '登录失败');
        }
      });
    };

    return { formRef, adminFormRef, form, adminForm, loading, activeTab, rules, adminRules, switchTab, handleLogin, handleAdminLogin };
  }
};
