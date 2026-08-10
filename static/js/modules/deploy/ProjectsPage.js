const ProjectsPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card" style="display:flex;flex-direction:column;height:calc(100vh - 120px)">
      <div class="page-header">
        <div class="section-title" style="margin:0">项目信息</div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-default" @click="refreshProjects">🔄 刷新清理</button>
          <button class="btn btn-primary" @click="showAddDialog">+ 新增项目</button>
        </div>
      </div>
      <div style="border-top:1px solid #f0f0f0"></div>

      <div v-if="loading" class="loading">加载中...</div>
      <div v-else-if="projects.length === 0" class="empty">暂无项目</div>
      <div v-else class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>项目名称</th>
              <th>描述</th>
              <th>环境数</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="project in projects" :key="project.id" :style="project.env_count === 0 ? 'background:#fff8f0' : ''">
              <td>[[ project.id ]]</td>
              <td><span class="tag tag-blue">[[ project.name ]]</span></td>
              <td>[[ project.description || '-' ]]</td>
              <td>
                <span v-if="project.env_count === 0" class="tag tag-red">0</span>
                <span v-else>[[ project.env_count ]]</span>
              </td>
              <td>[[ project.created_at ]]</td>
              <td>
                <button class="btn btn-default btn-sm" @click="showEditDialog(project)">编辑</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 新增/编辑对话框 -->
      <div v-if="dialogVisible" class="dialog-overlay" @click.self="dialogVisible = false">
        <div class="dialog" style="width: 450px;">
          <div class="detail-header">
            <div class="detail-title">[[ isEdit ? '编辑项目' : '新增项目' ]]</div>
            <button class="btn-close" @click="dialogVisible = false">×</button>
          </div>
          <div class="form-group">
            <label class="form-label">项目名称 *</label>
            <input class="form-input" v-model="formData.name" :disabled="isEdit" placeholder="如: ysh">
          </div>
          <div class="form-group">
            <label class="form-label">项目描述</label>
            <input class="form-input" v-model="formData.description" placeholder="如: 云商汇项目">
          </div>
          <div class="dialog-footer">
            <button class="btn btn-default" @click="dialogVisible = false">取消</button>
            <button class="btn btn-primary" @click="saveProject">确定</button>
          </div>
        </div>
      </div>
    </div>
  `,
  data() {
    return {
      projects: [],
      loading: false,
      dialogVisible: false,
      isEdit: false,
      formData: {
        id: null,
        name: '',
        description: ''
      }
    };
  },
  methods: {
    loadProjects() {
      this.loading = true;
      ajax('GET', '/api/project/list', null, (r) => {
        this.projects = r.data || [];
        this.loading = false;
      });
    },
    refreshProjects() {
      ajax('POST', '/api/project/refresh', null, (r) => {
        if (r.code === 200) {
          const count = r.data?.count || 0;
          if (count > 0) {
            showSuccess(r.msg || `已清理 ${count} 个空项目`);
          } else {
            showSuccess('没有需要清理的空项目');
          }
          this.loadProjects();
        } else {
          showError(r.msg || '刷新失败');
        }
      });
    },
    showAddDialog() {
      this.isEdit = false;
      this.formData = { id: null, name: '', description: '' };
      this.dialogVisible = true;
    },
    showEditDialog(project) {
      this.isEdit = true;
      this.formData = { ...project };
      this.dialogVisible = true;
    },
    saveProject() {
      if (!this.formData.name) {
        showWarning('请输入项目名称');
        return;
      }

      if (this.isEdit) {
        // 编辑
        ajax('POST', '/api/project/update', this.formData, (r) => {
          if (r.code === 200) {
            showSuccess('项目更新成功');
            this.dialogVisible = false;
            this.loadProjects();
          } else {
            showError(r.msg || '更新失败');
          }
        });
      } else {
        // 新增
        ajax('POST', '/api/admin/projects', { name: this.formData.name, description: this.formData.description }, (r) => {
          if (r.code === 200) {
            showSuccess('项目创建成功');
            this.dialogVisible = false;
            this.loadProjects();
          } else {
            showError(r.msg || '创建失败');
          }
        });
      }
    }
  },
  created() {
    this.loadProjects();
  }
};
