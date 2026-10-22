// 工具函数
function gv(id) {
  var el = document.getElementById(id);
  return el ? el.value.trim() : '';
}

function ajax(method, url, data, callback) {
  var xhr = new XMLHttpRequest();
  xhr.open(method, url, true);
  xhr.setRequestHeader('Content-Type', 'application/json');

  // 自动携带 Token
  var token = localStorage.getItem('auth_token');
  if (token) {
    xhr.setRequestHeader('Authorization', 'Bearer ' + token);
  }

  xhr.onload = function() {
    var res;
    try { res = JSON.parse(xhr.responseText); } catch(e) { res = { code: xhr.status, msg: '响应解析失败' }; }

    // 401 未登录 / Token 过期：清理本地态并跳转登录页（登录页自身不跳转）；
    // 仍回调调用方，确保 loading 等 UI 状态复位、错误信息可见（否则登录按钮会卡在「登录中」）
    if (xhr.status === 401) {
      localStorage.removeItem('auth_token');
      localStorage.removeItem('auth_expires');
      if (typeof authState !== 'undefined') {
        authState.isLoggedIn = false;
        authState.username = '';
        authState.permissions = [];
      }
      if (typeof router !== 'undefined' && router.currentRoute.value.path !== '/login') {
        router.push('/login');
      }
      if (callback) callback(res);
      return;
    }

    // 403 无权限：增强提示文案（角色降权后旧页面菜单与实际权限不一致，刷新后经 me() 更新状态），
    // 交回调统一处理，避免双重弹窗且保证调用方复位 loading
    if (xhr.status === 403 || res.code === 403) {
      res.msg = (res.msg || '无操作权限') + '，请刷新页面';
      if (callback) callback(res);
      return;
    }

    callback(res);
  };
  xhr.onerror = function() {
    // 网络异常：同样回调调用方（携带错误对象），保证 loading 复位与错误可见
    if (callback) callback({ code: -1, msg: '网络请求失败' });
  };
  xhr.send(data ? JSON.stringify(data) : null);
}

function toast(message, type) {
  var el = document.createElement('div');
  el.className = 'toast toast-' + type;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(function() { el.remove(); }, 3000);
}

// 按需加载脚本（同一 URL 只加载一次，失败不重试）：
// 用于 echarts 这类只有个别页面用的大库，避免所有页面首屏都为它付出阻塞下载
var __scriptCache = {};
function loadScriptOnce(url) {
  if (__scriptCache[url]) return __scriptCache[url];
  __scriptCache[url] = new Promise(function(resolve, reject) {
    var s = document.createElement('script');
    s.src = url;
    s.async = true;
    s.onload = function() { resolve(true); };
    s.onerror = function() { reject(new Error('脚本加载失败: ' + url)); };
    document.head.appendChild(s);
  });
  return __scriptCache[url];
}

// ─── SSE 多路复用 ─────────────────────────────────────────
// 浏览器对同一域名（HTTP/1.1）只允许 6 条并发连接，而平台页面挂着多条常驻 SSE
// （首页监控 / 服务列表 / 构建状态…），多开标签页后配额即被占满。
// SseHub 让整个标签页只占 1 条连接（/api/stream?topics=...），按 topic 分发给订阅者。
// topic 集合变化时自动重连（服务端会重发快照帧，页面状态自愈）。
var SseHub = (function () {
  var es = null;
  var subs = {};            // topic -> [{ onmessage, onopen, onerror }]
  var reconnectTimer = null;

  function fire(topic, key, arg) {
    var list = subs[topic];
    if (!list) return;
    list.slice().forEach(function (h) {
      try { if (h[key]) h[key](arg); } catch (e) { console.error('[SseHub]', e); }
    });
  }
  function fireAll(key) {
    Object.keys(subs).forEach(function (t) { fire(t, key); });
  }
  function reconnect() {
    if (es) { es.close(); es = null; }
    var topics = Object.keys(subs);
    if (!topics.length) return;
    var token = localStorage.getItem('auth_token') || '';
    var url = '/api/stream?topics=' + encodeURIComponent(topics.join(','))
      + '&token=' + encodeURIComponent(token);
    es = new EventSource(url);
    es.onopen = function () { fireAll('onopen'); };
    es.onmessage = function (e) {
      var d;
      try { d = JSON.parse(e.data); } catch (_) { return; }
      if (!d || !d.topic || d.topic === '__end__') {
        // 所有主题都自然结束：通知订阅方连接已断
        if (d && d.topic === '__end__') fireAll('onerror');
        return;
      }
      fire(d.topic, 'onmessage', d);
    };
    es.onerror = function () {
      // EventSource 自身会按同 URL 自动重连；这里只通知订阅方连接状态变化
      fireAll('onerror');
    };
  }
  function scheduleReconnect() {
    // 合并同一时刻的多次订阅/退订，避免反复建连
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(function () { reconnectTimer = null; reconnect(); }, 60);
  }
  function subscribe(topic, handlers) {
    var list = subs[topic] || (subs[topic] = []);
    list.push(handlers);
    scheduleReconnect();
    return function () { unsubscribe(topic, handlers); };
  }
  function unsubscribe(topic, handlers) {
    var list = subs[topic];
    if (!list) return;
    var i = list.indexOf(handlers);
    if (i >= 0) list.splice(i, 1);
    if (!list.length) delete subs[topic];
    scheduleReconnect();
  }
  return { subscribe: subscribe };
})();
