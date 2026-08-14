// 用户管理页组件
const UsersPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card">
      <div class="page-header">
        <div class="section-title" style="margin-bottom:0">用户管理</div>
        <div style="display:flex;gap:8px;align-items:center">
          <el-input v-model="keyword" placeholder="搜索：用户名 / 昵称 / 拼音（如 zhj、ceshi）"
            clearable style="width:280px" @input="onKeywordInput" @clear="onKeywordClear"></el-input>
          <el-button :loading="syncLoading" @click="handleSyncUsers">🔄 同步认证中心用户</el-button>
        </div>
      </div>

      <div class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>用户名</th>
              <th>昵称</th>
              <th>手机号</th>
              <th>邮箱</th>
              <th>角色</th>
              <th>状态</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading"><td colspan="9" class="loading">加载中...</td></tr>
            <tr v-else-if="!users.length"><td colspan="9" class="empty">暂无用户</td></tr>
            <tr v-for="u in users" :key="u.id">
              <td>[[ u.id ]]</td>
              <td>[[ u.username ]]</td>
              <td>[[ u.nickname || '-' ]]</td>
              <td>[[ u.phone || '-' ]]</td>
              <td>[[ u.email || '-' ]]</td>
              <td>
                <!-- 超级管理员：金色渐变标识；其他角色按类型显示 -->
                <el-tag v-if="u.role_name === '超级管理员'" size="small"
                  style="background:linear-gradient(135deg,#f6d365 0%,#fda085 100%);border:none;color:#8a4b00;font-weight:600;box-shadow:0 2px 6px rgba(246,211,101,.4)">
                  [[ u.role_name ]]
                </el-tag>
                <el-tag v-else :type="u.role_name === '管理员' ? 'danger' : u.role_name === '运维人员' ? '' : 'info'" size="small">
                  [[ u.role_name ]]
                </el-tag>
              </td>
              <td>
                <el-tag :type="u.is_active ? 'success' : 'danger'" size="small">
                  [[ u.is_active ? '启用' : '禁用' ]]
                </el-tag>
              </td>
              <td>[[ u.created_at ]]</td>
              <td>
                <el-button size="small" @click="openEdit(u)">编辑</el-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 编辑用户弹窗：平台字段（角色/停用）本地保存；昵称/手机/邮箱/新密码/TOTP 存储于认证中心 -->
      <el-dialog v-model="dialogVisible" title="编辑用户" width="540px" :close-on-click-modal="false">
        <el-form label-width="90px">
          <el-form-item label="用户名">
            <el-input v-model="form.username" disabled></el-input>
          </el-form-item>
          <el-form-item label="昵称">
            <el-input v-model="form.nickname" placeholder="同步到认证中心"></el-input>
          </el-form-item>
          <div style="margin:-6px 0 8px 90px;font-size:12px;color:#909399">以下字段存储于认证中心（authPlatform），保存后统一同步：</div>
          <el-form-item label="手机号">
            <el-input v-model="form.phone" placeholder="修改请直接编辑，清空则移除"></el-input>
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input v-model="form.email" placeholder="修改请直接编辑，清空则移除"></el-input>
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="form.password" type="password" show-password placeholder="留空不修改（管理员代改）"></el-input>
          </el-form-item>
          <el-form-item label="双因子TOTP">
            <div>
              <el-button size="small" @click="setupTotp">重置双因子</el-button>
              <div v-if="totpSecret" style="margin-top:6px">
                <div style="font-size:12px;color:#909399">用验证器 App 手动添加以下密钥，输入 6 位码确认：</div>
                <code style="word-break:break-all;font-size:12px">[[ totpSecret ]]</code>
                <div style="font-size:11px;color:#c0c4cc;word-break:break-all;margin:4px 0">[[ totpUrl ]]</div>
                <el-input v-model="form.totp_code" placeholder="6 位验证码" style="width:180px" maxlength="6"></el-input>
              </div>
            </div>
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="form.role_id" placeholder="请选择角色" style="width:100%">
              <el-option v-for="r in roles" :key="r.id" :label="r.name" :value="r.id"></el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-switch v-model="form.is_active" active-text="启用" inactive-text="禁用"></el-switch>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="dialogVisible = false">取 消</el-button>
          <el-button type="primary" :loading="saving" @click="handleSave">保 存</el-button>
        </template>
      </el-dialog>
    </div>
  `,
  setup() {
    const users = Vue.ref([]);
    const roles = Vue.ref([]);
    const loading = Vue.ref(false);
    const saving = Vue.ref(false);
    const dialogVisible = Vue.ref(false);
    const editId = Vue.ref(null);
    const form = Vue.reactive({ username: '', nickname: '', phone: '', email: '', password: '', role_id: '', is_active: true, totp_code: '' });
    const originalNickname = Vue.ref('');
    const originalPhone = Vue.ref('');
    const originalEmail = Vue.ref('');
    const totpSecret = Vue.ref('');
    const totpUrl = Vue.ref('');

    const syncLoading = Vue.ref(false);
    const keyword = Vue.ref('');
    let debounceTimer = null;

    // 防抖搜索（300ms）：昵称/用户名/拼音首拼子序列匹配由后端 /api/users/list?keyword= 完成
    const onKeywordInput = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => loadUsers(), 300);
    };
    const onKeywordClear = () => {
      clearTimeout(debounceTimer);
      loadUsers('');
    };

    const handleSyncUsers = () => {
      syncLoading.value = true;
      ajax('POST', '/api/users/sync', {}, (res) => {
        syncLoading.value = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg || '同步完成');
          loadUsers();
        } else {
          ElementPlus.ElMessage.error(res.msg || '同步失败');
        }
      });
    };

    const loadUsers = (kw) => {
      loading.value = true;
      const k = kw === undefined ? keyword.value : kw;
      keyword.value = k;  // 同步当前关键词（清空/外部触发时）
      ajax('GET', '/api/users/list' + (k ? '?keyword=' + encodeURIComponent(k) : ''), null, (res) => {
        loading.value = false;
        if (res.code === 200) users.value = res.data || [];
      });
    };

    const loadRoles = () => {
      ajax('GET', '/api/roles/list', null, (res) => {
        if (res.code === 200) roles.value = res.data || [];
      });
    };

    const openEdit = (u) => {
      editId.value = u.id;
      form.username = u.username;
      form.nickname = u.nickname || '';
      originalNickname.value = u.nickname || '';
      form.phone = u.phone || '';
      originalPhone.value = u.phone || '';
      form.email = u.email || '';
      originalEmail.value = u.email || '';
      form.password = '';
      form.totp_code = '';
      totpSecret.value = '';
      totpUrl.value = '';
      form.role_id = u.role_id || '';
      form.is_active = u.is_active;
      dialogVisible.value = true;
    };

    const setupTotp = () => {
      if (!editId.value) return;
      ajax('POST', '/api/users/totp-setup/' + editId.value, {}, (res) => {
        if (res.code === 200) {
          totpSecret.value = res.data.secret;
          totpUrl.value = res.data.otpauth_url;
          form.totp_code = '';
        } else {
          ElementPlus.ElMessage.error(res.msg || '生成失败');
        }
      });
    };

    const handleSave = () => {
      saving.value = true;
      // 1) 平台字段（角色/停用）走本地 users 表
      ajax('POST', '/api/users/update/' + editId.value, {
        role_id: form.role_id,
        is_active: form.is_active,
      }, (res) => {
        if (res.code !== 200) {
          saving.value = false;
          ElementPlus.ElMessage.error(res.msg);
          return;
        }
        // 2) 认证中心字段（昵称/手机/邮箱/新密码/TOTP）走 update-profile，成功后自动同步
        const profileBody = {};
        if (form.nickname !== originalNickname.value) profileBody.nickname = form.nickname;
        if (form.phone !== originalPhone.value) profileBody.phone = form.phone;
        if (form.email !== originalEmail.value) profileBody.email = form.email;
        if (form.password) profileBody.password = form.password;
        if (totpSecret.value) {
          profileBody.totp_secret = totpSecret.value;
          profileBody.totp_code = form.totp_code;
        }
        if (!Object.keys(profileBody).length) {
          saving.value = false;
          ElementPlus.ElMessage.success('保存成功');
          dialogVisible.value = false;
          loadUsers();
          return;
        }
        ajax('POST', '/api/users/profile/' + editId.value, profileBody, (res2) => {
          saving.value = false;
          if (res2.code === 200) {
            ElementPlus.ElMessage.success('保存成功（已同步认证中心）');
            dialogVisible.value = false;
            loadUsers();
          } else {
            ElementPlus.ElMessage.error(res2.msg || '认证中心更新失败');
          }
        });
      });
    };

    Vue.onMounted(() => {
      loadRoles();
      loadUsers();
    });

    return {
      users, roles, loading, saving, dialogVisible, form,
      totpSecret, totpUrl, setupTotp,
      syncLoading, handleSyncUsers, keyword, onKeywordInput, onKeywordClear,
      openEdit, handleSave,
    };
  }
};
