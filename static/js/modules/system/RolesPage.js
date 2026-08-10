// 角色管理页组件
const RolesPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card">
      <div class="page-header">
        <div class="section-title" style="margin-bottom:0">角色管理</div>
        <el-button type="primary" @click="openCreate">+ 新增角色</el-button>
      </div>

      <div class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>角色名</th>
              <th>描述</th>
              <th>权限数</th>
              <th>用户数</th>
              <th>类型</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading"><td colspan="8" class="loading">加载中...</td></tr>
            <tr v-else-if="!roles.length"><td colspan="8" class="empty">暂无角色</td></tr>
            <tr v-for="r in roles" :key="r.id">
              <td>[[ r.id ]]</td>
              <td><strong>[[ r.name ]]</strong></td>
              <td>[[ r.description ]]</td>
              <td><el-tag size="small">[[ r.permissions.length ]] 项</el-tag></td>
              <td>[[ r.user_count ]] 人</td>
              <td>
                <el-tag :type="r.is_builtin ? 'warning' : 'info'" size="small">
                  [[ r.is_builtin ? '内置' : '自定义' ]]
                </el-tag>
              </td>
              <td>[[ r.created_at ]]</td>
              <td>
                <el-button size="small" @click="openEdit(r)">编辑</el-button>
                <el-button size="small" type="danger" :disabled="r.is_builtin" @click="handleDelete(r)">删除</el-button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 新增/编辑角色弹窗 -->
      <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑角色' : '新增角色'" width="720px" :close-on-click-modal="false">
        <el-form label-width="80px">
          <el-form-item label="角色名">
            <el-input v-model="form.name" placeholder="请输入角色名称"></el-input>
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" placeholder="角色描述（可选）"></el-input>
          </el-form-item>
          <el-form-item label="权限配置">
            <div style="width:100%">
              <!-- 全选按钮 -->
              <div style="margin-bottom:8px;text-align:right">
                <el-button link size="small" type="primary" @click="toggleAll">
                  [[ isAllChecked ? '取消全选' : '全选' ]]
                </el-button>
              </div>
              <!-- 权限表格 -->
              <table class="data-table perm-table">
                <thead>
                  <tr>
                    <th style="width:140px">菜单名称</th>
                    <th style="width:90px;text-align:center">查看权限</th>
                    <th style="text-align:left">操作权限</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="row in permRows" :key="row.label">
                    <td>[[ row.label ]]</td>
                    <td style="text-align:center">
                      <el-checkbox
                        :model-value="hasCode(row.pageCode)"
                        @change="(val) => toggleCode(row.pageCode, val)">
                      </el-checkbox>
                    </td>
                    <td>
                      <template v-if="row.opCodes && row.opCodes.length">
                        <div style="display:flex;flex-wrap:wrap;gap:4px 12px">
                          <el-checkbox v-for="op in row.opCodes" :key="op.code"
                            :model-value="hasCode(op.code)"
                            @change="(val) => toggleCode(op.code, val)">
                            [[ op.label ]]
                          </el-checkbox>
                        </div>
                      </template>
                      <span v-else style="color:#c0c4cc">-</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
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
    const roles = Vue.ref([]);
    const loading = Vue.ref(false);
    const saving = Vue.ref(false);
    const dialogVisible = Vue.ref(false);
    const isEdit = Vue.ref(false);
    const editId = Vue.ref(null);
    const form = Vue.reactive({ name: '', description: '', permissions: [] });

    // 权限行定义：从后端动态加载（新增菜单自动同步）
    const permRows = Vue.ref([]);

    // 检查单个权限码是否已勾选
    const hasCode = (code) => form.permissions.includes(code);

    // 切换单个权限码
    const toggleCode = (code, checked) => {
      if (checked) {
        if (!form.permissions.includes(code)) form.permissions.push(code);
      } else {
        form.permissions = form.permissions.filter(c => c !== code);
      }
    };

    // 全部权限码（用于全选）
    const allCodes = Vue.computed(() => {
      const codes = [];
      permRows.value.forEach(row => {
        codes.push(row.pageCode);
        if (row.opCodes) row.opCodes.forEach(op => codes.push(op.code));
      });
      return codes;
    });

    const isAllChecked = Vue.computed(() => {
      return allCodes.value.length > 0 && allCodes.value.every(c => form.permissions.includes(c));
    });

    const toggleAll = () => {
      if (isAllChecked.value) {
        form.permissions = [];
      } else {
        form.permissions = [...allCodes.value];
      }
    };

    const loadRoles = () => {
      loading.value = true;
      ajax('GET', '/api/roles/list', null, (res) => {
        loading.value = false;
        if (res.code === 200) roles.value = res.data || [];
      });
    };

    const openCreate = () => {
      isEdit.value = false;
      editId.value = null;
      form.name = '';
      form.description = '';
      form.permissions = [];
      dialogVisible.value = true;
    };

    const openEdit = (r) => {
      isEdit.value = true;
      editId.value = r.id;
      form.name = r.name;
      form.description = r.description;
      form.permissions = [...r.permissions];
      dialogVisible.value = true;
    };

    const handleSave = () => {
      if (!form.name) {
        ElementPlus.ElMessage.warning('请输入角色名称');
        return;
      }
      saving.value = true;
      const url = isEdit.value
        ? '/api/roles/update/' + editId.value
        : '/api/roles/create';
      ajax('POST', url, {
        name: form.name,
        description: form.description,
        permissions: form.permissions,
      }, (res) => {
        saving.value = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg);
          dialogVisible.value = false;
          loadRoles();
        } else {
          ElementPlus.ElMessage.error(res.msg);
        }
      });
    };

    const handleDelete = (r) => {
      if (r.is_builtin) {
        ElementPlus.ElMessage.warning('内置角色不可删除');
        return;
      }
      ElementPlus.ElMessageBox.confirm(
        '确定要删除角色「' + r.name + '」吗？',
        '确认删除',
        { type: 'warning' }
      ).then(() => {
        ajax('POST', '/api/roles/delete/' + r.id, {}, (res) => {
          if (res.code === 200) {
            ElementPlus.ElMessage.success(res.msg);
            loadRoles();
          } else {
            ElementPlus.ElMessage.error(res.msg);
          }
        });
      }).catch(() => {});
    };

    Vue.onMounted(() => {
      loadRoles();
      // 动态加载权限行结构
      ajax('GET', '/api/roles/permissions', null, (res) => {
        if (res.code === 200 && res.data && res.data.rows) {
          permRows.value = res.data.rows;
        }
      });
    });

    return {
      roles, loading, saving, dialogVisible, isEdit, form,
      permRows, hasCode, toggleCode, isAllChecked, toggleAll,
      openCreate, openEdit, handleSave, handleDelete,
    };
  }
};
