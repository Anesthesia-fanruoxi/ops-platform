// ============================================================
// 服务信息页 mixin：发布前行级 diff 对比（与 NginxPage 同算法 + 大文件优化）
// 性能关键：先裁掉公共前/后缀，仅对中间变化区做 LCS；
// 展示层折叠相同行（变更前后各留 3 行上下文），避免大配置渲染全量 DOM 卡死页面
// ============================================================

const SvcMixinDiff = {
  data() {
    return {
      // 发布对比
      diffVisible: false,
      diffRows: [],
      diffStats: { added: 0, removed: 0, modified: 0 },
    };
  },
  methods: {
    _computeDiff(oldLines, newLines) {
      // 1. 裁公共前缀
      let start = 0;
      const minLen = Math.min(oldLines.length, newLines.length);
      while (start < minLen && oldLines[start] === newLines[start]) start++;
      // 2. 裁公共后缀
      let oldEnd = oldLines.length, newEnd = newLines.length;
      while (oldEnd > start && newEnd > start && oldLines[oldEnd - 1] === newLines[newEnd - 1]) { oldEnd--; newEnd--; }

      const stats = { added: 0, removed: 0, modified: 0 };
      const rows = [];
      // 前缀（same）
      for (let i = 0; i < start; i++) {
        rows.push({ type: 'same', oldText: oldLines[i], newText: newLines[i], oldLn: i + 1, newLn: i + 1 });
      }
      // 中间变化区
      const midOld = oldLines.slice(start, oldEnd);
      const midNew = newLines.slice(start, newEnd);
      const mid = Math.max(midOld.length, midNew.length) > 1500
        ? this._simpleDiff(midOld, midNew)
        : this._lcsDiff(midOld, midNew);
      stats.added += mid.stats.added;
      stats.removed += mid.stats.removed;
      stats.modified += mid.stats.modified;
      mid.rows.forEach((r) => {
        if (r.oldLn !== '') r.oldLn += start;
        if (r.newLn !== '') r.newLn += start;
        rows.push(r);
      });
      // 后缀（same）
      for (let i = oldEnd; i < oldLines.length; i++) {
        const j = i - oldEnd + newEnd;
        rows.push({ type: 'same', oldText: oldLines[i], newText: newLines[j], oldLn: i + 1, newLn: j + 1 });
      }
      return { rows: this._collapseSameRows(rows), stats };
    },

    // 折叠连续相同行：变更前后各保留 ctx 行上下文，其余折成占位行
    _collapseSameRows(rows, ctx = 3) {
      const keep = new Array(rows.length).fill(false);
      for (let i = 0; i < rows.length; i++) {
        if (rows[i].type !== 'same') {
          const lo = Math.max(0, i - ctx);
          const hi = Math.min(rows.length - 1, i + ctx);
          for (let j = lo; j <= hi; j++) keep[j] = true;
        }
      }
      const out = [];
      let i = 0;
      while (i < rows.length) {
        if (keep[i]) { out.push(rows[i]); i++; continue; }
        let j = i;
        while (j < rows.length && !keep[j]) j++;
        out.push({ type: 'fold', count: j - i });
        i = j;
      }
      return out;
    },

    // LCS 行级 diff（仅用于中间变化区）
    _lcsDiff(oldLines, newLines) {
      const m = oldLines.length, n = newLines.length;
      // 构建 LCS 表
      const dp = [];
      for (let i = 0; i <= m; i++) dp[i] = new Uint16Array(n + 1);
      for (let i = 1; i <= m; i++) {
        for (let j = 1; j <= n; j++) {
          dp[i][j] = oldLines[i - 1] === newLines[j - 1]
            ? dp[i - 1][j - 1] + 1
            : Math.max(dp[i - 1][j], dp[i][j - 1]);
        }
      }
      // 回溯生成 diff
      const stats = { added: 0, removed: 0, modified: 0 };
      const stack = [];
      let oi = m, ni = n;
      while (oi > 0 || ni > 0) {
        if (oi > 0 && ni > 0 && oldLines[oi - 1] === newLines[ni - 1]) {
          stack.push({ type: 'same', oldText: oldLines[oi - 1], newText: newLines[ni - 1], oldLn: oi, newLn: ni });
          oi--; ni--;
        } else if (ni > 0 && (oi === 0 || dp[oi][ni - 1] >= dp[oi - 1][ni])) {
          stack.push({ type: 'added', oldText: '', newText: newLines[ni - 1], oldLn: '', newLn: ni });
          stats.added++;
          ni--;
        } else {
          stack.push({ type: 'removed', oldText: oldLines[oi - 1], newText: '', oldLn: oi, newLn: '' });
          stats.removed++;
          oi--;
        }
      }
      stack.reverse();
      // 合并相邻 removed 块 + added 块 为 modified
      const rows = [];
      let i = 0;
      while (i < stack.length) {
        // same 行直接透传（变化区中部仍可能有相同行；缺少此分支会不推进 i 导致死循环）
        if (stack[i].type === 'same') { rows.push(stack[i++]); continue; }
        const removedBlock = [];
        while (i < stack.length && stack[i].type === 'removed') { removedBlock.push(stack[i]); i++; }
        const addedBlock = [];
        while (i < stack.length && stack[i].type === 'added') { addedBlock.push(stack[i]); i++; }
        if (removedBlock.length && addedBlock.length) {
          const pair = Math.min(removedBlock.length, addedBlock.length);
          for (let p = 0; p < pair; p++) {
            rows.push({
              type: 'modified',
              oldText: removedBlock[p].oldText, newText: addedBlock[p].newText,
              oldLn: removedBlock[p].oldLn, newLn: addedBlock[p].newLn,
            });
            stats.modified++;
            stats.removed--;
            stats.added--;
          }
          for (let p = pair; p < removedBlock.length; p++) rows.push(removedBlock[p]);
          for (let p = pair; p < addedBlock.length; p++) rows.push(addedBlock[p]);
        } else {
          rows.push(...removedBlock, ...addedBlock);
        }
      }
      return { rows, stats };
    },
    _simpleDiff(oldLines, newLines) {
      const rows = [];
      const stats = { added: 0, removed: 0, modified: 0 };
      const maxLen = Math.max(oldLines.length, newLines.length);
      for (let i = 0; i < maxLen; i++) {
        const oldLine = i < oldLines.length ? oldLines[i] : null;
        const newLine = i < newLines.length ? newLines[i] : null;
        if (oldLine === null) {
          rows.push({ type: 'added', oldText: '', newText: newLine, oldLn: '', newLn: i + 1 });
          stats.added++;
        } else if (newLine === null) {
          rows.push({ type: 'removed', oldText: oldLine, newText: '', oldLn: i + 1, newLn: '' });
          stats.removed++;
        } else if (oldLine === newLine) {
          rows.push({ type: 'same', oldText: oldLine, newText: newLine, oldLn: i + 1, newLn: i + 1 });
        } else {
          rows.push({ type: 'modified', oldText: oldLine, newText: newLine, oldLn: i + 1, newLn: i + 1 });
          stats.modified++;
        }
      }
      return { rows, stats };
    },
  },
};
