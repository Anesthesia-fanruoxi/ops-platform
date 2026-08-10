// 数据源管理页面 - MySQL自定义数据源CRUD
const DatasourcesPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
<div class="card">
  <div class="page-header">
    <div class="section-title" style="margin:0">MySQL 数据源</div>
    <div style="display:flex;gap:10px;align-items:center">
      <el-input v-model="searchText" placeholder="搜索数据源..." clearable size="default" style="width:220px" prefix-icon="Search" />
      <el-button type="primary" @click="openDialog(null)">+ 新增数据源</el-button>
    </div>
  </div>

  <el-table :data="filteredList" v-loading="loading" stripe style="width:100%" empty-text="暂无数据源">
    <el-table-column prop="name" label="名称" min-width="120" />
    <el-table-column label="连接地址" min-width="180">
      <template #default="{ row }">[[ row.host ]]:[[ row.port ]]</template>
    </el-table-column>
    <el-table-column prop="user" label="用户名" width="100" />
    <el-table-column prop="project" label="所属项目" width="110">
      <template #default="{ row }"><el-tag v-if="row.project" size="small" type="info">[[ row.project ]]</el-tag><span v-else style="color:#c0c4cc">-</span></template>
    </el-table-column>
    <el-table-column prop="env" label="环境" width="90">
      <template #default="{ row }"><el-tag v-if="row.env" size="small">[[ row.env ]]</el-tag><span v-else style="color:#c0c4cc">-</span></template>
    </el-table-column>
    <el-table-column prop="description" label="备注" min-width="140" show-overflow-tooltip>
      <template #default="{ row }">[[ row.description || '-' ]]</template>
    </el-table-column>
    <el-table-column prop="created_at" label="创建时间" width="160" />
    <el-table-column label="操作" width="200" fixed="right">
      <template #default="{ row }">
        <el-button size="small" @click="testConn(row)" :loading="testingId===row.id">测试</el-button>
        <el-button size="small" type="primary" @click="openDialog(row)">编辑</el-button>
        <el-popconfirm title="确认删除该数据源？" @confirm="remove(row)">
          <template #reference><el-button size="small" type="danger">删除</el-button></template>
        </el-popconfirm>
      </template>
    </el-table-column>
  </el-table>

  <!-- 新增/编辑弹窗 -->
  <el-dialog v-model="dialogVisible" :title="editingId ? '编辑数据源' : '新增数据源'" width="520px" :close-on-click-modal="false">
    <el-form label-width="90px">
      <el-form-item label="名称" required>
        <el-input v-model="form.name" placeholder="数据源名称，如: ysh-test-mysql" />
      </el-form-item>
      <el-form-item label="主机地址" required>
        <el-input v-model="form.host" placeholder="IP或域名" />
      </el-form-item>
      <el-form-item label="端口" required>
        <el-input-number v-model="form.port" :min="1" :max="65535" style="width:160px" />
      </el-form-item>
      <el-form-item label="用户名">
        <el-input v-model="form.user" placeholder="root" />
      </el-form-item>
      <el-form-item label="密码">
        <el-input v-model="form.password" type="password" show-password placeholder="数据库密码" />
      </el-form-item>
      <el-form-item label="所属项目">
        <el-input v-model="form.project" placeholder="可选，用于分组" />
      </el-form-item>
      <el-form-item label="环境">
        <el-input v-model="form.env" placeholder="可选，如: test、uat" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="testFormConn" :loading="testingForm">测试连接</el-button>
      <el-button @click="dialogVisible = false">取 消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保 存</el-button>
    </template>
  </el-dialog>
</div>
  `,
  data() {
    return {
      loading: false,
      list: [],
      searchText: '',
      dialogVisible: false,
      editingId: null,
      saving: false,
      testingId: null,
      testingForm: false,
      form: { name: '', host: '', port: 3306, user: 'root', password: '', project: '', env: '', description: '' },
    };
  },
  computed: {
    filteredList() {
      if (!this.searchText) return this.list;
      var kw = this.searchText.toLowerCase();
      return this.list.filter(function(s) {
        return (s.name || '').toLowerCase().includes(kw)
          || (s.host || '').toLowerCase().includes(kw)
          || (s.project || '').toLowerCase().includes(kw)
          || (s.env || '').toLowerCase().includes(kw);
      });
    }
  },
  methods: {
    load() {
      this.loading = true;
      ajax('GET', '/api/collation/datasources', null, r => {
        this.loading = false;
        this.list = (r.code === 200 ? r.data : []) || [];
      });
    },
    openDialog(row) {
      if (row) {
        this.editingId = row.id;
        this.form = { name: row.name, host: row.host, port: row.port, user: row.user, password: '', project: row.project || '', env: row.env || '', description: row.description || '' };
      } else {
        this.editingId = null;
        this.form = { name: '', host: '', port: 3306, user: 'root', password: '', project: '', env: '', description: '' };
      }
      this.dialogVisible = true;
    },
    save() {
      if (!this.form.name || !this.form.name.trim()) { ElementPlus.ElMessage.warning('请输入数据源名称'); return; }
      if (!this.form.host || !this.form.host.trim()) { ElementPlus.ElMessage.warning('请输入主机地址'); return; }
      this.saving = true;
      var payload = Object.assign({}, this.form, { port: this.form.port || 3306 });
      // 编辑时密码留空表示不修改
      if (this.editingId && !payload.password) delete payload.password;
      var self = this;
      if (this.editingId) {
        ajax('PUT', '/api/collation/datasources/' + this.editingId, payload, function(r) {
          self.saving = false;
          if (r.code === 200) { ElementPlus.ElMessage.success('更新成功'); self.dialogVisible = false; self.load(); }
          else ElementPlus.ElMessage.error(r.msg || '更新失败');
        });
      } else {
        ajax('POST', '/api/collation/datasources', payload, function(r) {
          self.saving = false;
          if (r.code === 200) { ElementPlus.ElMessage.success('创建成功'); self.dialogVisible = false; self.load(); }
          else ElementPlus.ElMessage.error(r.msg || '创建失败');
        });
      }
    },
    remove(row) {
      ajax('DELETE', '/api/collation/datasources/' + row.id, null, r => {
        if (r.code === 200) { ElementPlus.ElMessage.success('已删除'); this.load(); }
        else ElementPlus.ElMessage.error(r.msg || '删除失败');
      });
    },
    testConn(row) {
      this.testingId = row.id;
      ajax('POST', '/api/collation/datasources/test', { host: row.host, port: row.port, user: row.user, password: '' }, r => {
        this.testingId = null;
        if (r.code === 200) ElementPlus.ElMessage.success('连接成功');
        else ElementPlus.ElMessage.error(r.msg || '连接失败');
      });
    },
    testFormConn() {
      if (!this.form.host) { ElementPlus.ElMessage.warning('请先输入主机地址'); return; }
      this.testingForm = true;
      ajax('POST', '/api/collation/datasources/test', { host: this.form.host, port: this.form.port, user: this.form.user, password: this.form.password }, r => {
        this.testingForm = false;
        if (r.code === 200) ElementPlus.ElMessage.success('连接成功');
        else ElementPlus.ElMessage.error(r.msg || '连接失败');
      });
    }
  },
  created() { this.load(); }
};
