const NginxPage = {
  compilerOptions: { delimiters: ['[[', ']]'] },
  template: `
    <div class="card" style="display:flex;flex-direction:column;height:calc(100vh - 120px)">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
          <div class="section-title" style="margin:0">Nginx配置文件</div>
          <el-button type="primary" :loading="syncing" @click="syncConfigs" size="small">
            📥 同步
          </el-button>
          <el-button v-if="syncing && !progressVisible" type="primary" link @click="reopenSyncLog">
            查看日志
          </el-button>
          <el-radio-group v-model="selectedProject" size="small" style="margin-left:8px">
            <el-radio label="">全部</el-radio>
            <el-radio v-for="p in projects" :key="p" :label="p">[[ p ]]</el-radio>
          </el-radio-group>
        </div>
        <div class="header-actions">
          <el-input v-model="searchText" placeholder="搜索文件名..." clearable size="small" style="width:200px" />
        </div>
      </div>

      <el-table :data="filteredConfigs" v-loading="loading" stripe border style="width:100%;flex:1"
                :header-cell-style="{ background: '#f5f7fa', color: '#606266', fontWeight: 'bold' }">
        <template #empty>
          <el-empty :description="configs.length === 0 ? '暂无配置文件，请先同步' : '没有匹配的配置文件'" :image-size="80" />
        </template>
        <el-table-column type="index" label="#" width="50" align="center" />
        <el-table-column label="文件名" min-width="300">
          <template #default="scope">
            <el-button type="primary" link @click="viewFile(scope.row)" style="font-family:monospace">
              [[ scope.row.file_name ]]
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="项目" width="140" align="center">
          <template #default="scope">
            <el-tag v-if="matchProject(scope.row.file_name)" type="primary" size="small">
              [[ matchProject(scope.row.file_name) ]]
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="synced_at" label="同步时间" width="170">
          <template #default="scope">
            <span style="font-size:12px;color:#909399">[[ scope.row.synced_at ]]</span>
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top:auto;padding-top:8px;font-size:13px;color:#909399">共 [[ filteredConfigs.length ]] / [[ configs.length ]] 个配置文件</div>
    </div>

    <!-- 文件内容弹框 -->
    <el-dialog v-model="fileVisible" :title="currentFile.file_name" width="1000px" top="5vh"
               :close-on-click-modal="!isEditing" :close-on-press-escape="!isEditing"
               @opened="onFileOpened" @close="onFileClose">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <template v-if="!isEditing">
          <el-input v-model="searchKeyword" placeholder="搜索内容..." clearable size="small" prefix-icon="Search"
                    style="width:260px" @input="onSearchInput" @keydown.enter="searchNext" ref="searchInput" />
          <el-button size="small" @click="searchNext" :disabled="!searchKeyword">下一个</el-button>
          <span v-if="searchKeyword && matchCount > 0" style="font-size:12px;color:#909399">[[ matchCount ]] 处匹配</span>
          <span v-if="searchKeyword && matchCount === 0" style="font-size:12px;color:#f56c6c">无匹配</span>
          <div style="flex:1"></div>
          <el-button size="small" type="primary" plain @click="copyContent">📋 复制内容</el-button>
          <el-button v-if="canPush" size="small" type="warning" plain @click="startEdit">✏️ 编辑</el-button>
        </template>
        <template v-else>
          <div style="flex:1"></div>
          <span v-if="isContentModified" style="font-size:12px;color:#e6a23c">● 内容已修改</span>
          <el-button size="small" @click="cancelEdit">取消</el-button>
          <el-button size="small" type="primary" :loading="pushing" @click="saveAndPush" :disabled="!isContentModified">💾 保存并推送</el-button>
        </template>
      </div>
      <!-- 只读模式 -->
      <div v-show="!isEditing" class="nginx-code-viewer" ref="codeViewer" style="height:58vh;overflow:auto">
        <pre style="margin:0"><code class="hljs language-nginx" v-html="displayContent"></code></pre>
      </div>
      <!-- 编辑模式 -->
      <div v-show="isEditing" style="height:58vh">
        <textarea ref="editArea" v-model="editContent" style="width:100%;height:100%;resize:none;font-family:Consolas,Monaco,monospace;font-size:13px;line-height:1.5;padding:12px;border:1px solid #dcdfe6;border-radius:4px;box-sizing:border-box;background:#fafafa;tab-size:4;outline:none" spellcheck="false" @input="onEditInput" @keydown="onEditKeydown"></textarea>
      </div>
      <template #footer>
        <div style="font-size:12px;color:#909399;display:flex;gap:16px">
          <span>MD5: [[ currentFile.md5 ]]</span>
          <span>同步时间: [[ currentFile.synced_at ]]</span>
        </div>
      </template>
    </el-dialog>

    <!-- 保存对比弹框 -->
    <el-dialog v-model="diffVisible" width="1200px" top="3vh" :close-on-click-modal="false" :close-on-press-escape="false"
               title="⚠️ 确认推送并 Reload Nginx">
      <div style="margin-bottom:10px;padding:10px 14px;background:#fff7e6;border:1px solid #ffe58f;border-radius:4px;font-size:13px;color:#ad6800">
        此操作将覆盖服务器上的 <b>[[ currentFile.file_name ]]</b> 文件，并自动执行 nginx -t 测试和 nginx -s reload。请确认以下修改无误。
      </div>
      <div style="margin-bottom:8px;display:flex;gap:16px;font-size:12px;color:#909399">
        <span>新增 <span style="display:inline-block;width:12px;height:12px;background:#e6ffec;border:1px solid #b7f5c8;vertical-align:middle;margin:0 2px"></span></span>
        <span>删除 <span style="display:inline-block;width:12px;height:12px;background:#ffebe9;border:1px solid #f5b7b7;vertical-align:middle;margin:0 2px"></span></span>
        <span>修改 <span style="display:inline-block;width:12px;height:12px;background:#fff8e1;border:1px solid #f5e0b7;vertical-align:middle;margin:0 2px"></span></span>
        <div style="flex:1"></div>
        <span>[[ diffStats.added ]] 行新增，[[ diffStats.removed ]] 行删除，[[ diffStats.modified ]] 行修改</span>
      </div>
      <div class="diff-container" style="height:55vh;overflow:auto;border:1px solid #e8e8e8;border-radius:4px">
        <table class="diff-table">
          <colgroup>
            <col style="width:46px"><col><col style="width:46px"><col>
          </colgroup>
          <tbody>
            <tr v-for="(row, i) in diffRows" :key="i" :class="'diff-row diff-' + row.type">
              <td class="diff-ln">[[ row.oldLn ]]</td>
              <td class="diff-cell diff-cell-old"><pre>[[ row.oldText ]]</pre></td>
              <td class="diff-ln">[[ row.newLn ]]</td>
              <td class="diff-cell diff-cell-new"><pre>[[ row.newText ]]</pre></td>
            </tr>
          </tbody>
        </table>
      </div>
      <template #footer>
        <el-button @click="diffVisible = false">返回编辑</el-button>
        <el-button type="primary" :loading="pushing" @click="doPush">确认推送并 Reload</el-button>
      </template>
    </el-dialog>

    <!-- 同步进度弹框 -->
    <el-dialog v-model="progressVisible" width="700px" :close-on-click-modal="false" :close-on-press-escape="false"
               :show-close="true" title="Nginx配置同步">
      <div class="deploy-log" ref="progressLogContainer" style="max-height:400px;overflow-y:auto">
        <div v-for="(log, i) in progressLogs" :key="i" :class="'log-line log-' + (log.level || 'info').toLowerCase()">
          <span class="log-time">[[ log.time || '' ]]</span>
          <span :class="'log-level lvl-' + (log.level || 'info').toLowerCase()">[[ log.level || 'INFO' ]]</span>
          <span v-if="log.step" class="log-step">[[ log.step ]]</span>
          <span class="log-msg">[[ log.message || log.msg || '' ]]</span>
        </div>
        <div v-if="progressDone" :class="'log-line log-' + (progressSuccess ? 'done' : 'error')">
          <span class="log-msg">[[ progressSuccess ? '=== 同步完成 ===' : '=== 同步失败 ===' ]]</span>
        </div>
      </div>
    </el-dialog>
  `,
  data() {
    return {
      loading: false,
      syncing: false,
      configs: [],
      filteredConfigs: [],
      projects: [],
      selectedProject: '',
      searchText: '',
      progressVisible: false,
      progressLogs: [],
      progressDone: false,
      progressSuccess: false,
      eventSource: null,
      fileVisible: false,
      currentFile: {},
      rawContent: '',
      highlightedContent: '',
      displayContent: '',
      searchKeyword: '',
      matchCount: 0,
      _keyHandler: null,
      // 编辑模式
      isEditing: false,
      editContent: '',
      originalContent: '',
      pushing: false,
      // 对比
      diffVisible: false,
      diffRows: [],
      diffStats: { added: 0, removed: 0, modified: 0 }
    };
  },
  watch: {
    selectedProject() { this.applyFilter(); },
    searchText() { this.applyFilter(); }
  },
  computed: {
    isContentModified() {
      return this.editContent !== this.originalContent;
    },
    canPush() {
      return this.$auth.hasPermission('op:nginx_push');
    }
  },
  methods: {
    loadProjects() {
      ajax('GET', '/api/admin/projects', null, (r) => {
        this.projects = (r.data || []).map(p => p.name);
      });
    },
    loadConfigs() {
      this.loading = true;
      ajax('GET', '/api/nginx/list', null, (r) => {
        this.loading = false;
        this.configs = r.data || [];
        this.applyFilter();
      });
    },
    matchProject(fileName) {
      for (var p of this.projects) {
        if (fileName.startsWith(p)) return p;
      }
      return '';
    },
    applyFilter() {
      var proj = this.selectedProject;
      var search = this.searchText.toLowerCase().trim();
      this.filteredConfigs = this.configs.filter(function(c) {
        if (proj && !c.file_name.startsWith(proj)) return false;
        if (search && c.file_name.toLowerCase().indexOf(search) === -1) return false;
        return true;
      });
    },
    syncConfigs() {
      var self = this;
      ajax('POST', '/api/nginx/sync', {}, function(r) {
        if (r.code === 200) {
          self.syncing = true;
          self.progressLogs = [];
          self.progressDone = false;
          self.progressSuccess = false;
          self.progressVisible = true;
          self.connectSSE();
        } else {
          showError(r.msg || '同步启动失败');
        }
      });
    },
    reopenSyncLog() {
      this.progressLogs = [];
      this.progressDone = false;
      this.progressSuccess = false;
      this.progressVisible = true;
      this.connectSSE();
    },
    connectSSE() {
      var self = this;
      if (self.eventSource) { self.eventSource.close(); }
      var token = localStorage.getItem('auth_token') || '';
      var es = new EventSource('/api/deploy/stream?action=nginx-sync&token=' + encodeURIComponent(token));
      self.eventSource = es;
      es.onmessage = function(e) {
        var d = JSON.parse(e.data);
        if (d.done) {
          self.progressDone = true;
          self.progressSuccess = d.success !== false;
          es.close();
          self.eventSource = null;
          self.syncing = false;
          if (self.progressSuccess) {
            self.loadConfigs();
          }
          return;
        }
        self.progressLogs.push(d);
        self.$nextTick(function() {
          var c = self.$refs.progressLogContainer;
          if (c) c.scrollTop = c.scrollHeight;
        });
      };
      es.onerror = function() {
        es.close();
        self.eventSource = null;
        self.syncing = false;
        self.progressDone = true;
        self.progressSuccess = false;
        self.progressLogs.push({ level: 'ERROR', message: 'SSE连接失败，无法获取同步进度', time: '' });
      };
    },
    onSearchInput() {
      this.updateDisplayContent();
    },
    searchNext() {
      var viewer = this.$refs.codeViewer;
      if (!viewer) return;
      var mark = viewer.querySelector('.search-current');
      if (mark) {
        mark.classList.remove('search-current');
        var next = mark.nextElementSibling;
        while (next) {
          if (next.tagName === 'MARK') { next.classList.add('search-current'); next.scrollIntoView({block:'center'}); return; }
          next = next.nextElementSibling;
        }
        var first = viewer.querySelector('mark');
        if (first) { first.classList.add('search-current'); first.scrollIntoView({block:'center'}); }
      } else {
        var first = viewer.querySelector('mark');
        if (first) { first.classList.add('search-current'); first.scrollIntoView({block:'center'}); }
      }
    },
    updateDisplayContent() {
      var html = this.highlightedContent;
      var kw = (this.searchKeyword || '').trim();
      if (!kw) { this.displayContent = html; this.matchCount = 0; return; }
      // 在已高亮的HTML中搜索，需要跳过HTML标签
      var result = '', count = 0, i = 0, kwLower = kw.toLowerCase();
      while (i < html.length) {
        if (html[i] === '<') {
          var end = html.indexOf('>', i);
          if (end === -1) { result += html.substring(i); break; }
          result += html.substring(i, end + 1);
          i = end + 1;
        } else if (html[i] === '&') {
          var semi = html.indexOf(';', i);
          if (semi === -1) { result += html[i]; i++; continue; }
          var entity = html.substring(i, semi + 1);
          var ch = this.decodeEntity(entity);
          if (ch === null) { result += entity; i = semi + 1; continue; }
          // 尝试从当前位置匹配
          var textAhead = this.extractText(html, i);
          if (textAhead.toLowerCase().indexOf(kwLower) === 0) {
            count++;
            var cls = count === 1 ? 'search-current' : '';
            result += '<mark class="search-mark ' + cls + '">' + entity;
            var consumed = entity.length;
            for (var c = 1; c < kw.length; c++) {
              var nEntity = this.nextEntity(html, i + consumed);
              if (nEntity) { result += nEntity; consumed += nEntity.length; }
              else { result += html[i + consumed]; consumed++; }
            }
            result += '</mark>';
            i += consumed;
          } else {
            result += entity;
            i = semi + 1;
          }
        } else {
          var textAhead = this.extractText(html, i);
          if (textAhead.toLowerCase().indexOf(kwLower) === 0) {
            count++;
            var cls = count === 1 ? 'search-current' : '';
            result += '<mark class="search-mark ' + cls + '">';
            for (var c = 0; c < kw.length; c++) {
              var nEntity = this.nextEntity(html, i);
              if (nEntity) { result += nEntity; i += nEntity.length; }
              else { result += html[i]; i++; }
            }
            result += '</mark>';
          } else {
            result += html[i]; i++;
          }
        }
      }
      this.matchCount = count;
      this.displayContent = result;
      this.$nextTick(function() {
        var viewer = this.$refs.codeViewer;
        var cur = viewer ? viewer.querySelector('.search-current') : null;
        if (cur) cur.scrollIntoView({block:'center'});
      }.bind(this));
    },
    extractText(html, start) {
      var text = '', i = start;
      while (i < html.length && text.length < 50) {
        if (html[i] === '<') { var end = html.indexOf('>', i); if (end === -1) break; i = end + 1; }
        else if (html[i] === '&') { var semi = html.indexOf(';', i); if (semi === -1) { text += html[i]; i++; }
          else { var ch = this.decodeEntity(html.substring(i, semi+1)); text += (ch||html[i]); i = semi+1; } }
        else { text += html[i]; i++; }
      }
      return text;
    },
    nextEntity(html, i) {
      if (html[i] === '&') { var semi = html.indexOf(';', i); if (semi !== -1) return html.substring(i, semi+1); }
      if (html[i] === '<') return null;
      return html[i];
    },
    decodeEntity(entity) {
      var map = {'&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'",'&nbsp;':' '};
      return map[entity] !== undefined ? map[entity] : null;
    },
    copyContent() {
      var self = this;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(this.rawContent).then(function() {
          showSuccess('内容已复制到剪贴板');
        }).catch(function() { self.fallbackCopy(); });
      } else { self.fallbackCopy(); }
    },
    fallbackCopy() {
      var ta = document.createElement('textarea');
      ta.value = this.rawContent;
      ta.style.cssText = 'position:fixed;left:-9999px';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); showSuccess('内容已复制到剪贴板'); }
      catch(e) { showError('复制失败，请手动复制'); }
      document.body.removeChild(ta);
    },
    onFileOpened() {
      var self = this;
      this._keyHandler = function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
          e.preventDefault();
          if (self.$refs.searchInput) self.$refs.searchInput.focus();
        }
        if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
          e.preventDefault();
          self.selectAllContent();
        }
      };
      document.addEventListener('keydown', this._keyHandler);
    },
    onFileClose() {
      if (this._keyHandler) {
        document.removeEventListener('keydown', this._keyHandler);
        this._keyHandler = null;
      }
      this.searchKeyword = '';
      this.matchCount = 0;
      this.isEditing = false;
      this.editContent = '';
      this.originalContent = '';
      this.diffVisible = false;
      this.diffRows = [];
      this.diffStats = { added: 0, removed: 0, modified: 0 };
    },
    selectAllContent() {
      var viewer = this.$refs.codeViewer;
      if (!viewer) return;
      var range = document.createRange();
      range.selectNodeContents(viewer.querySelector('code'));
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    },
    viewFile(config) {
      ajax('GET', '/api/nginx/file/' + config.id, null, (r) => {
        if (r.code === 200) {
          this.currentFile = r.data;
          this.rawContent = r.data.content || '';
          this.searchKeyword = '';
          this.matchCount = 0;
          if (window.hljs) {
            try {
              this.highlightedContent = window.hljs.highlight(this.rawContent, { language: 'nginx' }).value;
            } catch(e) {
              this.highlightedContent = this.escapeHtml(this.rawContent);
            }
          } else {
            this.highlightedContent = this.escapeHtml(this.rawContent);
          }
          this.displayContent = this.highlightedContent;
          this.fileVisible = true;
        } else {
          showError(r.msg || '加载失败');
        }
      });
    },
    escapeHtml(text) {
      return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    },
    // ─── 编辑模式 ─────────────────────────────────
    startEdit() {
      this.originalContent = this.rawContent;
      this.editContent = this.rawContent;
      this.isEditing = true;
      this.$nextTick(function() {
        if (this.$refs.editArea) this.$refs.editArea.focus();
      }.bind(this));
    },
    cancelEdit() {
      if (this.isContentModified) {
        ElementPlus.ElMessageBox.confirm('内容已修改，确定放弃吗？', '提示', {
          confirmButtonText: '放弃',
          cancelButtonText: '继续编辑',
          type: 'warning'
        }).then(() => {
          this.isEditing = false;
          this.editContent = '';
          this.originalContent = '';
        }).catch(() => {});
      } else {
        this.isEditing = false;
        this.editContent = '';
        this.originalContent = '';
      }
    },
    onEditInput() {
      // 仅用于触发 isContentModified 计算属性更新
    },
    onEditKeydown(e) {
      // Ctrl+/ 切换注释
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        var ta = this.$refs.editArea;
        if (!ta) return;
        var val = ta.value;
        var start = ta.selectionStart;
        var end = ta.selectionEnd;

        // 找到选中区域覆盖的行范围
        var lineStart = val.lastIndexOf('\n', start - 1) + 1;
        var lineEnd = val.indexOf('\n', end);
        if (lineEnd === -1) lineEnd = val.length;

        var selected = val.substring(lineStart, lineEnd);
        var lines = selected.split('\n');

        // 判断是添加注释还是删除注释（所有行都已注释才删除）
        var allCommented = lines.every(function(l) { return l.trim() === '' || l.trimStart().startsWith('#'); });

        var newLines = lines.map(function(line) {
          if (allCommented) {
            // 删除注释: 去掉行首 # 或 #
            return line.replace(/^(\s*)# ?/, '$1');
          } else {
            // 添加注释
            return '# ' + line;
          }
        });

        var newText = newLines.join('\n');
        var before = val.substring(0, lineStart);
        var after = val.substring(lineEnd);
        ta.value = before + newText + after;
        this.editContent = ta.value;

        // 恢复选区
        ta.selectionStart = lineStart;
        ta.selectionEnd = lineStart + newText.length;
        ta.focus();
      }
      // Tab 缩进
      if (e.key === 'Tab') {
        e.preventDefault();
        var ta2 = this.$refs.editArea;
        var s = ta2.selectionStart;
        var en = ta2.selectionEnd;
        var v = ta2.value;
        ta2.value = v.substring(0, s) + '    ' + v.substring(en);
        this.editContent = ta2.value;
        ta2.selectionStart = ta2.selectionEnd = s + 4;
        ta2.focus();
      }
    },
    // ─── 修改对比 ───────────────────────────
    _computeDiff(oldLines, newLines) {
      // LCS-based line diff
      var m = oldLines.length, n = newLines.length;
      // 优化：对于超大文件，使用简化算法
      var maxLen = Math.max(m, n);
      if (maxLen > 5000) {
        return this._simpleDiff(oldLines, newLines);
      }
      // 构建 LCS 表
      var dp = [];
      for (var i = 0; i <= m; i++) {
        dp[i] = new Uint16Array(n + 1);
      }
      for (var i = 1; i <= m; i++) {
        for (var j = 1; j <= n; j++) {
          dp[i][j] = oldLines[i-1] === newLines[j-1]
            ? dp[i-1][j-1] + 1
            : Math.max(dp[i-1][j], dp[i][j-1]);
        }
      }
      // 回溯生成 diff
      var rows = [], stats = { added: 0, removed: 0, modified: 0 };
      var oi = m, ni = n;
      var stack = [];
      while (oi > 0 || ni > 0) {
        if (oi > 0 && ni > 0 && oldLines[oi-1] === newLines[ni-1]) {
          stack.push({ type: 'same', oldText: oldLines[oi-1], newText: newLines[ni-1], oldLn: oi, newLn: ni });
          oi--; ni--;
        } else if (ni > 0 && (oi === 0 || dp[oi][ni-1] >= dp[oi-1][ni])) {
          stack.push({ type: 'added', oldText: '', newText: newLines[ni-1], oldLn: '', newLn: ni });
          stats.added++;
          ni--;
        } else {
          stack.push({ type: 'removed', oldText: oldLines[oi-1], newText: '', oldLn: oi, newLn: '' });
          stats.removed++;
          oi--;
        }
      }
      stack.reverse();
      // 合并相邻的 removed 块 + added 块 为 modified
      var rows = [];
      var i = 0;
      while (i < stack.length) {
        // 收集连续的 removed 行
        var removedBlock = [];
        while (i < stack.length && stack[i].type === 'removed') {
          removedBlock.push(stack[i]);
          i++;
        }
        // 收集连续的 added 行
        var addedBlock = [];
        while (i < stack.length && stack[i].type === 'added') {
          addedBlock.push(stack[i]);
          i++;
        }
        // 配对 removed + added 为 modified
        if (removedBlock.length > 0 && addedBlock.length > 0) {
          var pairCount = Math.min(removedBlock.length, addedBlock.length);
          for (var p = 0; p < pairCount; p++) {
            rows.push({
              type: 'modified',
              oldText: removedBlock[p].oldText, newText: addedBlock[p].newText,
              oldLn: removedBlock[p].oldLn, newLn: addedBlock[p].newLn
            });
            stats.modified++;
            stats.removed--;
            stats.added--;
          }
          // 多余的 removed
          for (var p = pairCount; p < removedBlock.length; p++) {
            rows.push(removedBlock[p]);
          }
          // 多余的 added
          for (var p = pairCount; p < addedBlock.length; p++) {
            rows.push(addedBlock[p]);
          }
        } else {
          // 没有配对，直接输出
          for (var r = 0; r < removedBlock.length; r++) rows.push(removedBlock[r]);
          for (var a = 0; a < addedBlock.length; a++) rows.push(addedBlock[a]);
        }
        // 输出 same 行
        while (i < stack.length && stack[i].type === 'same') {
          rows.push(stack[i]);
          i++;
        }
      }
      return { rows: rows, stats: stats };
    },
    _simpleDiff(oldLines, newLines) {
      // 简化版 diff（用于超大文件）：逐行对比
      var rows = [], stats = { added: 0, removed: 0, modified: 0 };
      var maxLen = Math.max(oldLines.length, newLines.length);
      for (var i = 0; i < maxLen; i++) {
        var oldLine = i < oldLines.length ? oldLines[i] : null;
        var newLine = i < newLines.length ? newLines[i] : null;
        if (oldLine === null) {
          rows.push({ type: 'added', oldText: '', newText: newLine, oldLn: '', newLn: i+1 });
          stats.added++;
        } else if (newLine === null) {
          rows.push({ type: 'removed', oldText: oldLine, newText: '', oldLn: i+1, newLn: '' });
          stats.removed++;
        } else if (oldLine === newLine) {
          rows.push({ type: 'same', oldText: oldLine, newText: newLine, oldLn: i+1, newLn: i+1 });
        } else {
          rows.push({ type: 'modified', oldText: oldLine, newText: newLine, oldLn: i+1, newLn: i+1 });
          stats.modified++;
        }
      }
      return { rows: rows, stats: stats };
    },
    saveAndPush() {
      // 计算 diff 并弹出对比确认框
      var oldLines = this.originalContent.split('\n');
      var newLines = this.editContent.split('\n');
      var diff = this._computeDiff(oldLines, newLines);
      this.diffRows = diff.rows;
      this.diffStats = diff.stats;
      this.diffVisible = true;
    },
    doPush() {
      var self = this;
      self.pushing = true;
      ajax('POST', '/api/nginx/push/' + self.currentFile.id, { content: self.editContent }, function(r) {
        self.pushing = false;
        if (r.code === 200) {
          showSuccess('推送成功：' + (r.data.message || 'Nginx 已 reload'));
          self.diffVisible = false;
          self.isEditing = false;
          // 更新当前文件信息
          self.currentFile.md5 = r.data.md5;
          self.currentFile.synced_at = r.data.synced_at;
          self.rawContent = self.editContent;
          self.originalContent = '';
          self.editContent = '';
          // 重新高亮显示
          if (window.hljs) {
            try {
              self.highlightedContent = window.hljs.highlight(self.rawContent, { language: 'nginx' }).value;
            } catch(e) {
              self.highlightedContent = self.escapeHtml(self.rawContent);
            }
          } else {
            self.highlightedContent = self.escapeHtml(self.rawContent);
          }
          self.displayContent = self.highlightedContent;
          // 刷新列表
          self.loadConfigs();
        } else {
          showError(r.msg || '推送失败');
        }
      });
    }
  },
  created() {
    this.loadProjects();
    this.loadConfigs();
  }
};
