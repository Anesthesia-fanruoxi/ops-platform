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
