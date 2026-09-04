// ============================================================
// 服务信息页共享基础：日志行高亮工具 + 日志行列表子组件 + 模块级变量
// 加载顺序：先于 serviceinfo/ 目录下其余文件加载
// ============================================================

// 日志行 HTML 高亮（模块级纯函数，运行日志终端与日志文件渲染共用）
function svcEscapeHtml(text) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function svcHighlightLine(line, searchWord) {
  let html = svcEscapeHtml(line == null ? '' : line);
  // 行首时间戳着色：2026-08-12 13:57:47.101 或 13:57:47.101
  html = html.replace(/^(\s*)((\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)/,
    '$1<span class="svc-log-time">$2</span>');
  // Java 方法/行数着色：[类.方法,行号] 或 [lambda$x,行号]
  html = html.replace(/\[([^\],\[\s]+),(\d+)\]/g,
    '[<span class="svc-log-method">$1</span>,<span class="svc-log-line">$2</span>]');
  // 搜索高亮（split/join 方式，避免转义问题）
  if (searchWord) {
    const q = svcEscapeHtml(searchWord);
    if (q) html = html.split(q).join('<mark style="background:#e6a23c;color:#1e1e1e;border-radius:2px">' + q + '</mark>');
  }
  return html;
}

// 日志行列表（独立子组件）：父组件因输入框按键等其他状态重渲染时，
// 只要 lines/searchWord 引用不变就整体跳过，避免重跑全量行高亮
const SvcLogLines = {
  name: 'SvcLogLines',
  props: {
    lines: { type: Array, default: () => [] },
    searchWord: { type: String, default: '' },
  },
  template: `<div v-for="line in lines" :key="line.k" :id="'logline-' + line.k" :class="{ 'svc-log-match': isMatch(line) }" v-html="hl(line)"></div>`,
  methods: {
    hl(line) { return svcHighlightLine(line.t, this.searchWord); },
    isMatch(line) {
      if (!this.searchWord) return false;
      return line.t.toLowerCase().includes(this.searchWord.toLowerCase());
    },
  },
};

// YAML 段落参考线用：等宽字体单字符宽度（首次渲染时实测，之后复用）
let svcCfgCharW = 0;
let svcLogKeySeq = 0;  // 日志行稳定 key 计数器（splice 后剩余行 key 不变，Vue 只 diff 增删行）
