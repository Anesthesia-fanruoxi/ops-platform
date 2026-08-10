// ============================================================
// 全局认证状态
// ============================================================
const authState = Vue.reactive({
  isLoggedIn: false,
  username: '',
  nickname: '',
  roleName: '',
  permissions: [],
  isSuperAdmin: false,
  hasPermission(code) {
    return this.permissions.includes(code);
  }
});

// 认证状态是否已恢复（页面加载时等待异步验证，期间路由守卫不拦截）
let authReady = false;

// ============================================================
// 菜单配置（二级分组，权限码关联；组内全不可见时整组隐藏）
// ============================================================
const menuConfig = [
  {
    key: 'deploy', icon: '🚀', label: '部署平台',
    children: [
      { path: '/create/project', label: '新增项目', permission: 'page:create' },
      { path: '/create/env',     label: '新增环境', permission: 'page:create' },
      { path: '/create/service', label: '新增服务', permission: 'page:create' },
    ]
  },
  {
    key: 'project', icon: '📋', label: '项目管理',
    children: [
      { path: '/projects', label: '项目信息', permission: 'page:projects' },
      { path: '/manage',   label: '环境信息', permission: 'page:manage' },
    ]
  },
  {
    key: 'nginx', icon: '🌐', label: 'Nginx',
    children: [
      { path: '/nginx', label: 'Nginx配置', permission: 'page:nginx' },
    ]
  },
  {
    key: 'mysql', icon: '🗄️', label: 'MySQL',
    children: [
      { path: '/datasources', label: '数据源', permission: 'page:datasources' },
      { path: '/collation',   label: '字符集排序修正', permission: 'page:collation' },
    ]
  },
  {
    key: 'cicd', icon: '🔧', label: 'CI/CD',
    children: [
      { path: '/cicd', label: 'CI/CD管理', permission: 'page:cicd' },
      { path: '/schedule', label: '调度中心', permission: 'page:cicd' },
    ]
  },
  {
    key: 'system', icon: '⚙️', label: '系统管理',
    children: [
      { path: '/users',    label: '用户管理', permission: 'page:users' },
      { path: '/roles',    label: '角色管理', permission: 'page:roles' },
      { path: '/settings', label: '系统设置', permission: 'page:settings' },
    ]
  },
];

// 扁平化所有叶子菜单项
function flatMenuItems() {
  var items = [];
  menuConfig.forEach(function(g) { items = items.concat(g.children); });
  return items;
}

// 查找第一个有权限的菜单项
function findFirstAllowed() {
  return flatMenuItems().find(function(m) { return authState.hasPermission(m.permission); });
}

// ============================================================
// 路由配置
// ============================================================
const routes = [
  { path: '/login',    component: LoginPage,    meta: { title: '登录', noAuth: true } },
  { path: '/',         redirect: '/create/project' },
  { path: '/create',   redirect: '/create/project' },
  { path: '/create/project', component: CreateProject,    meta: { title: '新增项目', permission: 'page:create' } },
  { path: '/create/env',     component: CreateEnvironment, meta: { title: '新增环境', permission: 'page:create' } },
  { path: '/create/service', component: CreateService,     meta: { title: '新增服务', permission: 'page:create' } },
  { path: '/projects', component: ProjectsPage, meta: { title: '项目信息', permission: 'page:projects' } },
  { path: '/manage',   component: ManagePage,   meta: { title: '环境信息', permission: 'page:manage' } },
  { path: '/nginx',    component: NginxPage,    meta: { title: 'Nginx配置', permission: 'page:nginx' } },
  { path: '/datasources', component: DatasourcesPage, meta: { title: '数据源', permission: 'page:datasources' } },
  { path: '/collation', component: CollationPage, meta: { title: '字符集排序修正', permission: 'page:collation' } },
  { path: '/cicd',     component: CicdConfigPage, meta: { title: 'CI/CD管理', permission: 'page:cicd' } },
  { path: '/schedule', component: SchedulePage, meta: { title: '调度中心', permission: 'page:cicd' } },
  { path: '/settings', component: SettingsPage, meta: { title: '系统设置', permission: 'page:settings' } },
  { path: '/users',    component: UsersPage,    meta: { title: '用户管理', permission: 'page:users' } },
  { path: '/roles',    component: RolesPage,    meta: { title: '角色管理', permission: 'page:roles' } },
];

const router = VueRouter.createRouter({
  history: VueRouter.createWebHashHistory(),
  routes
});

// ============================================================
// 路由守卫
// ============================================================
router.beforeEach((to, from, next) => {
  // 认证状态尚未恢复（首次加载）→ 放行，等 tryRestoreAuth 完成后再处理
  if (!authReady) {
    return next();
  }

  // 登录页不需要认证
  if (to.meta.noAuth) {
    // 已登录访问登录页 → 跳转主页
    if (authState.isLoggedIn) {
      const firstAllowed = findFirstAllowed();
      return next(firstAllowed ? firstAllowed.path : '/create/project');
    }
    return next();
  }

  // 未登录 → 跳转登录页
  if (!authState.isLoggedIn) {
    return next('/login');
  }

  // 已登录但无权限 → 跳转第一个有权限的页面
  if (to.meta.permission && !authState.hasPermission(to.meta.permission)) {
    const firstAllowed = findFirstAllowed();
    if (firstAllowed) {
      return next(firstAllowed.path);
    }
    return next('/login');
  }

  next();
});

// ============================================================
// 启动时尝试恢复登录状态
// ============================================================
function tryRestoreAuth(callback) {
  var token = localStorage.getItem('auth_token');
  if (!token) {
    callback();
    return;
  }

  // 请求后端验证 Token 并获取用户信息（服务端滑动续期为准，不依赖本地过期时间）
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/api/auth/me', true);
  xhr.setRequestHeader('Authorization', 'Bearer ' + token);
  xhr.onload = function() {
    if (xhr.status === 200) {
      var res = JSON.parse(xhr.responseText);
      if (res.code === 200 && res.data) {
        authState.isLoggedIn = true;
        authState.username = res.data.username;
        authState.nickname = res.data.nickname || '';
        authState.roleName = res.data.role_name || '';
        authState.permissions = res.data.permissions || [];
        authState.isSuperAdmin = !!res.data.is_super_admin;
      }
    } else {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('auth_expires');
    }
    callback();
  };
  xhr.onerror = function() { callback(); };
  xhr.send();
}

// ============================================================
// 实时刷新权限（切回页面时从后端同步最新权限）
// ============================================================
function refreshPermissions() {
  if (!authState.isLoggedIn) return;
  var token = localStorage.getItem('auth_token');
  if (!token) return;

  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/api/auth/me', true);
  xhr.setRequestHeader('Authorization', 'Bearer ' + token);
  xhr.onload = function() {
    if (xhr.status === 200) {
      var res = JSON.parse(xhr.responseText);
      if (res.code === 200 && res.data) {
        authState.permissions = res.data.permissions || [];
        authState.roleName = res.data.role_name || '';
        authState.isSuperAdmin = !!res.data.is_super_admin;
        // 检查当前页面是否还有权限，无则跳转
        var currentPath = router.currentRoute.value.path;
        var currentMenu = flatMenuItems().find(m => m.path === currentPath);
        if (currentMenu && !authState.hasPermission(currentMenu.permission)) {
          var firstAllowed = findFirstAllowed();
          if (firstAllowed) {
            router.replace(firstAllowed.path);
          } else {
            authState.isLoggedIn = false;
            localStorage.removeItem('auth_token');
            router.push('/login');
          }
        }
      }
    } else if (xhr.status === 401) {
      authState.isLoggedIn = false;
      localStorage.removeItem('auth_token');
      localStorage.removeItem('auth_expires');
      router.push('/login');
    }
  };
  xhr.send();
}

// 用户切回页面时刷新权限
document.addEventListener('visibilitychange', function() {
  if (document.visibilityState === 'visible') {
    refreshPermissions();
  }
});

// ============================================================
// Vue App 初始化
// ============================================================
const app = Vue.createApp({
  compilerOptions: {
    delimiters: ['[[', ']]']
  },
  data() {
    return {
      auth: authState,
      menuItems: menuConfig,
      // 风琴式菜单：当前展开的分组 key（同时只展开一个）
      openGroupKey: null,
      // 已打开的标签页（{path, title, name}），切换不刷新、关闭销毁实例
      openedTabs: [],
      // 修改密码弹窗
      pwdDialogVisible: false,
      pwdForm: { old_password: '', new_password: '', confirm_password: '' },
      pwdLoading: false,
    };
  },
  computed: {
    // 根据权限过滤菜单（组内全不可见时整组隐藏）
    visibleMenuGroups() {
      return this.menuItems.map(group => ({
        ...group,
        children: group.children.filter(item => this.auth.hasPermission(item.permission))
      })).filter(group => group.children.length > 0);
    },
    // keep-alive 需要缓存的组件名（与已打开标签对应；关闭标签即从缓存剔除并销毁实例）
    cachedViews() {
      return this.openedTabs.map(t => t.name);
    }
  },
  watch: {
    '$route'(to) {
      document.title = (to.meta.title || '运维平台') + ' - 运维平台';
      // 路由切换时自动展开所属分组
      this.expandGroupByPath(to.path);
      // 登记标签页
      this.addTab(to);
    },
    // 权限被实时收回时，清理无权的标签页
    'auth.permissions'() {
      this.pruneTabsByPermission();
    }
  },
  mounted() {
    // 初始加载时设置浏览器标题，并展开当前路由对应分组
    document.title = (this.$route.meta.title || '运维平台') + ' - 运维平台';
    this.expandGroupByPath(this.$route.path);
    this.addTab(this.$route);
  },
  methods: {
    handleLogout() {
      ajax('POST', '/api/auth/logout', {}, () => {});
      localStorage.removeItem('auth_token');
      localStorage.removeItem('auth_expires');
      authState.isLoggedIn = false;
      authState.username = '';
      authState.nickname = '';
      authState.roleName = '';
      authState.permissions = [];
      authState.isSuperAdmin = false;
      this.openedTabs = [];
      router.push('/login');
    },
    handleUserCommand(cmd) {
      if (cmd === 'logout') this.handleLogout();
      else if (cmd === 'password') this.openPwdDialog();
    },
    openPwdDialog() {
      this.pwdForm = { old_password: '', new_password: '', confirm_password: '' };
      this.pwdDialogVisible = true;
    },
    handleChangePwd() {
      if (!this.pwdForm.old_password || !this.pwdForm.new_password) {
        ElementPlus.ElMessage.warning('请填写完整');
        return;
      }
      if (this.pwdForm.new_password.length < 6) {
        ElementPlus.ElMessage.warning('新密码长度不能少于6位');
        return;
      }
      if (this.pwdForm.new_password !== this.pwdForm.confirm_password) {
        ElementPlus.ElMessage.warning('两次密码输入不一致');
        return;
      }
      this.pwdLoading = true;
      ajax('POST', '/api/auth/change-password', {
        old_password: this.pwdForm.old_password,
        new_password: this.pwdForm.new_password,
      }, (res) => {
        this.pwdLoading = false;
        if (res.code === 200) {
          ElementPlus.ElMessage.success(res.msg);
          this.pwdDialogVisible = false;
          // 强制重新登录
          localStorage.removeItem('auth_token');
          localStorage.removeItem('auth_expires');
          authState.isLoggedIn = false;
          authState.permissions = [];
          router.push('/login');
        } else {
          ElementPlus.ElMessage.error(res.msg);
        }
      });
    },
    // 风琴式分组：点击切换展开（同时只展开一个）
    toggleGroup(key) {
      this.openGroupKey = this.openGroupKey === key ? null : key;
    },
    // 根据路由路径展开所属分组
    expandGroupByPath(path) {
      const group = this.menuItems.find(g => g.children.some(c => c.path === path));
      if (group) this.openGroupKey = group.key;
    },
    // 登记当前路由对应的标签页（同路径去重）
    addTab(to) {
      if (!to.meta || !to.meta.title || to.meta.noAuth) return;
      const matched = to.matched && to.matched[0];
      const comp = matched && matched.components && matched.components.default;
      const name = comp && comp.name;
      if (!name) return;
      if (!this.openedTabs.some(t => t.path === to.path)) {
        this.openedTabs.push({ path: to.path, title: to.meta.title, name });
      }
    },
    // 切换标签页（组件被 keep-alive 缓存，状态原样保留）
    switchTab(tab) {
      if (this.$route.path !== tab.path) router.push(tab.path);
    },
    // 关闭标签页：从缓存剔除使实例销毁；关闭当前页则切换到相邻标签
    closeTab(tab) {
      const idx = this.openedTabs.findIndex(t => t.path === tab.path);
      if (idx === -1) return;
      this.openedTabs.splice(idx, 1);
      if (this.$route.path === tab.path) {
        const next = this.openedTabs[idx] || this.openedTabs[idx - 1];
        if (next) router.push(next.path);
      }
    },
    // 清理已无权限的标签页（当前页无权时跳转首个有权页面）
    pruneTabsByPermission() {
      const allowed = this.openedTabs.filter(t => {
        const m = flatMenuItems().find(x => x.path === t.path);
        return m && authState.hasPermission(m.permission);
      });
      if (allowed.length !== this.openedTabs.length) {
        this.openedTabs = allowed;
        if (!this.openedTabs.some(t => t.path === this.$route.path)) {
          const first = findFirstAllowed();
          if (first) router.replace(first.path);
        }
      }
    },
    // 获取第一个有权限的路径（用于默认跳转）
    getFirstAllowedPath() {
      const item = findFirstAllowed();
      return item ? item.path : '/login';
    }
  }
});

// 注册全局组件（确保 name 存在，keep-alive 的 include 按组件名匹配缓存）
[['CreateProject', CreateProject], ['CreateEnvironment', CreateEnvironment],
 ['CreateService', CreateService], ['ProjectsPage', ProjectsPage], ['ManagePage', ManagePage],
 ['NginxPage', NginxPage], ['DatasourcesPage', DatasourcesPage], ['CollationPage', CollationPage],
 ['CicdConfigPage', CicdConfigPage], ['SchedulePage', SchedulePage],
 ['SettingsPage', SettingsPage], ['LoginPage', LoginPage],
 ['UsersPage', UsersPage], ['RolesPage', RolesPage]
].forEach(function(pair) {
  pair[1].name = pair[1].name || pair[0];
  app.component(pair[0], pair[1]);
});

app.use(ElementPlus);
app.use(router);
app.config.globalProperties.$auth = authState;

// 启动：先恢复认证状态，再挂载
tryRestoreAuth(() => {
  // 标记认证状态已恢复，路由守卫开始生效
  authReady = true;

  var currentPath = router.currentRoute.value.path;
  if (authState.isLoggedIn) {
    // 已登录但在登录页 → 跳转主页（防止套娃）
    if (currentPath === '/login') {
      var firstAllowed = findFirstAllowed();
      router.replace(firstAllowed ? firstAllowed.path : '/create/project');
    }
    // 已登录且路由正常 → 无需任何操作，保留当前路由
  } else {
    // 未登录 → 跳转登录页
    if (currentPath !== '/login') {
      router.push('/login');
    }
  }
  app.mount('#app');
});
