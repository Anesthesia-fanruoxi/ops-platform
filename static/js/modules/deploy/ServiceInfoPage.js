// ============================================================
// 服务信息页（部署管理）— 入口组装文件
// 原单文件约 3100 行，已按功能拆分至 serviceinfo/ 子目录：
//   svc-shared.js           工具函数 + SvcLogLines 日志行子组件
//   svc-styles.js           页面样式（动态注入，带版本防缓存）
//   mixin-servicelist.js    项目/环境/收藏/服务卡片 SSE/重启
//   mixin-quickbuild.js     快捷部署构建弹窗（分支/服务/类型）
//   mixin-buildprogress.js  构建进度抽屉 + 环境构建状态 SSE
//   mixin-log.js            运行日志弹窗（SSE 追踪/搜索定位/全屏）
//   mixin-logfile.js        日志目录（NFS 直连）+ 文件内容搜索定位
//   mixin-nacos.js          Nacos 配置业务（加载/编辑/发布）
//   mixin-nacosrender.js    Nacos 渲染（高亮/搜索定位/YAML 参考线）
//   mixin-diff.js           发布前行级 diff 对比
//   mixin-misc.js           环境变量/部署 YAML/选择服务目录/复制
//   svc-template.js         页面模板字符串（window.SvcTemplate）
// 依赖 base.html 按上述顺序 <script> 引入（无构建，顶层 const 全局可见）
// ============================================================

const ServiceInfoPage = {
  name: 'ServiceInfoPage',
  compilerOptions: { delimiters: ['[[', ']]'] },
  components: { SvcLogLines },
  mixins: [SvcMixinServiceList, SvcMixinQuickBuild, SvcMixinBuildProgress, SvcMixinLog, SvcMixinLogfile, SvcMixinNacos, SvcMixinNacosRender, SvcMixinDiff, SvcMixinMisc],
  template: window.SvcTemplate,
};
