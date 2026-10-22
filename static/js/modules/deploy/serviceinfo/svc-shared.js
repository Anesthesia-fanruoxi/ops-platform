// ============================================================
// 服务信息页共享基础：日志行高亮工具 + 日志行列表子组件 + 模块级变量
// 加载顺序：先于 serviceinfo/ 目录下其余文件加载
// ============================================================

// 日志行 HTML 高亮（模块级纯函数，运行日志终端与日志文件渲染共用）
// current=true：当前定位到的那处匹配（深黄）；其余匹配用浅黄，避免满屏都是强高亮
function svcEscapeHtml(text) {
  return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function svcHighlightLine(line, searchWord, current) {
  let html = svcEscapeHtml(line == null ? '' : line);
  // 行首时间戳着色：2026-08-12 13:57:47.101 或 13:57:47.101
  html = html.replace(/^(\s*)((\d{4}-\d{2}-\d{2} )?\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?)/,
    '$1<span class="svc-log-time">$2</span>');
  // Java 方法/行数着色：[类.方法,行号] 或 [lambda$x,行号]
  html = html.replace(/\[([^\],\[\s]+),(\d+)\]/g,
    '[<span class="svc-log-method">$1</span>,<span class="svc-log-line">$2</span>]');
  // 搜索高亮（split/join 方式，避免转义问题）：当前匹配深黄，其他匹配浅黄
  if (searchWord) {
    const q = svcEscapeHtml(searchWord);
    if (q) {
      const style = current
        ? 'background:#e6a23c;color:#1e1e1e;border-radius:2px'
        : 'background:#f3dfa2;color:#1e1e1e;border-radius:2px';
      html = html.split(q).join('<mark style="' + style + '">' + q + '</mark>');
    }
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
    // 当前定位到的那行匹配的 key（未定位时为 null）
    currentKey: { type: [Number, String], default: null },
  },
  template: `<div v-for="line in lines" :key="line.k" :id="'logline-' + line.k" :class="{ 'svc-log-match': isMatch(line), 'svc-log-current': isCurrent(line) }" v-html="hl(line)"></div>`,
  methods: {
    hl(line) { return svcHighlightLine(line.t, this.searchWord, this.isCurrent(line)); },
    isMatch(line) {
      if (!this.searchWord) return false;
      return line.t.toLowerCase().includes(this.searchWord.toLowerCase());
    },
    isCurrent(line) {
      return this.currentKey != null && line.k === this.currentKey;
    },
  },
};

// YAML 段落参考线用：等宽字体单字符宽度（首次渲染时实测，之后复用）
let svcCfgCharW = 0;
let svcLogKeySeq = 0;  // 日志行稳定 key 计数器（splice 后剩余行 key 不变，Vue 只 diff 增删行）

// 日志流渲染参数（运行日志弹窗 / 独立标签页共用）
// 暂停追踪：新行只进积压区不渲染；积压达到上限后断开连接，由用户「重连」重新拉取
const SVC_LOG_MAX_LINES = 1000;      // 已渲染行上限（超出丢最旧）
const SVC_LOG_BACKLOG_MAX = 500;     // 暂停积压上限
const SVC_LOG_DRAIN_BATCH = 20;      // 恢复追踪时每批吐出条数
const SVC_LOG_DRAIN_MS = 500;        // 每批间隔（毫秒）→ 约 20 条 / 0.5 秒
const SVC_LOG_BACKLOG_HARD_MAX = 2000; // 追平积压期间新行继续排队的安全上限
