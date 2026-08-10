# authPlatform 接入文档 · 业务端对接实现

> 本文为 `authPlatform/doc/接入文档.md` 的**追加章节**（§7），描述**接入平台侧（业务端）**的对接实现，以 ops-platform 为例。
> 与服务端 API 文档（接入文档.md §1-§6）配套阅读；业务端源码对应 `ops-platform/modules/system/auth_platform.py`（客户端）与 `modules/system/user_api.py`（接口层）。
>
> 更新：2026-08-07 ｜ 适用业务端实现：ops-platform（Python/Flask）

---

## 7. 业务端对接实现（以 ops-platform 为例）

服务端（authPlatform）只提供 API，接入平台需自行实现：接入配置、签名客户端、登录代理、用户同步、资料变更转发。以下为 ops-platform 的完整实现逻辑，可直接作为其他平台（CMDB 等）的对接参考。

### 7.1 接入配置

业务端在「平台设置」中维护 3 个配置项（settings 表，`platform` 组）：

| 配置键 | 说明 |
|---|---|
| `authplatform_base_url` | 认证中心地址（如 `http://192.168.100.128:8080`）；**留空 = 未接入，回退本地账号登录** |
| `authplatform_platform_id` | 在认证中心「平台管理」注册得到的平台标识（如 `ops-platform`） |
| `authplatform_secret` | 平台独立加密盐（仅创建时展示一次），用于请求签名 |

**未接入语义**：三个键任一为空 → `get_config()` 返回 `None` → 登录走本地账号校验（`users` 表），用户同步按钮隐藏/报「未配置认证中心」。接入后原本地账号（`auth_source='local'`，如超级管理员）仍可用，两者并存。

### 7.2 签名客户端

与接入文档 §2 签名协议一一对应（HMAC-SHA256，三个请求头）：

```python
import hashlib, hmac, time, json, requests

def get_config():
    """读取接入配置；任一必填项缺失返回 None（未接入）"""
    from modules.system.settings_service import get_setting
    base_url = (get_setting('authplatform_base_url') or '').strip().rstrip('/')
    platform_id = (get_setting('authplatform_platform_id') or '').strip()
    secret = (get_setting('authplatform_secret') or '').strip()
    if not base_url or not platform_id or not secret:
        return None
    return {'base_url': base_url, 'platform_id': platform_id, 'secret': secret}

def _sign(secret, method, uri, timestamp, body_bytes):
    # sign = HMAC-SHA256(secret, method|完整RequestURI|timestamp|sha256(body)hex)
    msg = f"{method}|{uri}|{timestamp}|{hashlib.sha256(body_bytes).hexdigest()}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

def _request(cfg, method, uri, body=None):
    body_bytes = json.dumps(body).encode('utf-8') if body is not None else b''
    ts = str(int(time.time()))
    headers = {
        'X-Platform-Id': cfg['platform_id'],
        'X-Timestamp': ts,
        'X-Sign': _sign(cfg['secret'], method, uri, ts, body_bytes),
        'Content-Type': 'application/json',
    }
    url = cfg['base_url'] + uri
    resp = requests.post(url, data=body_bytes, headers=headers, timeout=5) if method == 'POST' \
        else requests.get(url, headers=headers, timeout=5)
    resp.raise_for_status()
    return resp.json()
```

要点：
- `uri` 必须含 query 原样（如 `/api/users?platform_id=ops-platform`），与 §2 一致。
- 调用异常**不把细节透传用户**（可能含内网 URL），统一返回「认证服务调用失败，请稍后再试」并记日志。

### 7.3 登录代理与用户映射

**登录流程**（业务端 `auth_api.login`）：

```
用户提交 {username, password}
   │
   ├─ 已接入 authPlatform？──否──▶ 本地账号校验（users 表，原逻辑）
   │   └─ 是
   ▼
1. verify_login()：POST /api/auth/verify（兼容旧格式，等价 username_password）
   │   ┌ 多步登录（响应是 ticket 非 token）→ 提示「该账号需要二次验证，当前版本暂不支持」
   │   ┌ 1010 强制改密 → 返回 403「需先修改密码」
   │   ┌ 业务错误码映射：1003→401、1004/1006→403、1005→429、1001→401、1002→503、1007→400、1009→403
   │   └ 认证中心调用异常 → 503「认证服务调用失败」
2. 成功 → get_or_create_sso_user(user_info) 本地映射：
   │   - auth_uid 已映射 → 返回本地用户（同步昵称/手机/邮箱）
   │   - 本地存在同名 username 且 auth_source='sso' → 重绑 auth_uid（断链修复，沿用角色）
   │   - 同名 local 原生账号 → 不接管（保持本地账号），返回 None
   │   - 都没有 → 新建 sso 用户：password_hash=''、默认角色「只读用户」
3. 本地签发 Redis 会话（secrets.token_urlsafe(32)）：
   │   - 不保存 authPlatform 的 token（平台不吊销，生命周期平台自管）
   │   - 单点登录语义：同一本地用户重新登录清除旧会话
   ▼
返回登录成功（本地 token + 用户信息）
```

**用户映射字段**：`auth_uid`（认证中心 uid，唯一）、`auth_source='sso'`、`password_hash=''`（无本地密码，登录永远走认证中心）、`is_active`（合并规则见 §7.4）。

### 7.4 用户同步全流程（核心）

**触发方式**：用户管理页「同步认证中心用户」按钮，或 `POST /api/users/sync`（需 `op:users` 权限）。

**拉取**：`list_users()` → `GET /api/users?platform_id=xxx`（带签名）。认证中心只返回**授权给本平台**的用户（未授权/不存在/认证中心管理员一律不可见）。

**同步三阶段**（`sync_users()`，一次同步事务内完成）：

```
拉取到授权用户列表
   │
   ├─ ① synced_users 只读镜像（uid 唯一，upsert）
   │     有则更新（username/nickname/phone/email/status/last_synced_at），无则插入
   │     ← 该表仅「同步接口」写入，平台侧只读展示（GET /api/users/synced）
   │
   ├─ ② users 表复制（供平台单独维护权限）
   │     - 按 auth_uid 关联：更新 username/nickname/phone/email
   │     - is_active 合并规则：local.is_active = 认证中心status AND 本地is_active
   │         · 任一禁用即禁用；认证中心启用【不】复活平台已禁
   │         · 新用户无平台禁用历史，跟随认证中心状态
   │     - 同名 local 原生账号：跳过 users 复制（防越权接管），synced_users 仍保留
   │     - sso 同名旧账号：重绑 auth_uid（断链修复）
   │
   └─ ③ 全量镜像覆盖：删除认证中心已不返回的记录（取消授权/移除用户）
          - synced_users：多余即删（纯镜像）
          - users 表 auth_source='sso'：取消授权【一律彻底删除】（含已分配管理员角色的）
            重新授权后再次同步自动重建（默认「只读用户」角色）
```

**同步结果消息**（返回给前端提示）：
```
同步完成：新增 N 个、更新 M 个；平台用户新增 X 个、更新 Y 个；移除已取消授权 A 个；平台用户删除 B 个；跳过同名本地账号 C 个（...）
```

**权限说明**：删除多余仅作用于 `auth_source='sso'` 的用户；本地账号（含超级管理员）不受同步影响。超管在 `user_api` 层不可修改/删除/禁用；管理员角色**不受保护**（可编辑/删除/被同步删除）。

**查询**：`GET /api/users/synced`（只读展示 synced_users，任意登录用户可访问，无额外权限码）。

### 7.5 资料变更转发

非平台特性字段（昵称/手机/邮箱/密码/TOTP 重新绑定）由平台处理变更、数据存认证中心：

```
POST /api/users/profile/{user_id}（需 page:users + op:users 权限）
   ├─ 校验：用户存在、非超管、必须是 auth_source='sso'（有 auth_uid）
   ├─ 平台侧逻辑校验：密码策略（check_password_policy）、TOTP 重新绑定需 6 位验证码确认
   ├─ 转发 update_profile() → POST /api/auth/update-profile（§4.5）
   └─ 认证中心落库成功 → 平台【再同步一次用户表】（sync_users）更新本地副本
```

- 字段规则与服务端 §4.5 一致：email/phone 不传=不修改、`""`=清空、非空=更新；password 非空则代改；totp_secret 非空=绑定、`""`=清除。
- **平台特性字段**（角色、停用状态）不走认证中心，仍由平台本地 `POST /api/users/update/{id}` 维护。

### 7.6 权限与角色模型

| 用户类型 | 来源 | 密码 | 平台角色 | 保护 |
|---|---|---|---|---|
| 超级管理员 | 本地（`auth_source='local'`，`is_super_admin=1`） | 本地 | 内置「超级管理员」 | **不可修改/删除/禁用**，不参与同步 |
| 管理员 | 认证中心同步或本地 | 认证中心（sso）/本地 | 内置「管理员」（全权限） | 无保护，可编辑/删除 |
| 普通用户 | 认证中心同步 | 认证中心 | 默认「只读用户」，可再分配 | 无保护 |
| 同名冲突 | 本地原生账号与认证中心同名 | 本地 | 保持本地 | 同步不接管 |

- 角色/权限是**平台本地**概念（roles/permissions 表），认证中心不参与；权限校验由平台 `require_permission` 实时完成（每次请求实时查 DB，角色变更/禁用即时生效）。
- 认证中心禁用/删除用户：经同步置平台禁用/删除后，由平台实时校验在下一次请求拦截（旧 token 立即 401）。

### 7.7 业务端接口清单

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/users/sync` | `op:users` | 触发同步（§7.4） |
| GET | `/api/users/synced` | 任意登录用户 | 只读展示 synced_users |
| POST | `/api/users/profile/{id}` | `page:users` + `op:users` | 资料变更转发认证中心（§7.5） |
| POST | `/api/auth/login` | 匿名 | 登录（接入后走代理校验） |
| POST | `/api/auth/admin-login` | 匿名 | 超级管理员本地登录（逃生通道，不走认证中心） |
| PUT | `/api/users/update/{id}` | `op:users` | 平台特性字段（角色/停用） |

### 7.8 时序图

**登录**：
```
用户 → 平台登录页 → POST /api/auth/login
  → [已接入] verify_login → POST /api/auth/verify（签名）
  ← token + user（不落库认证中心 token）
  → get_or_create_sso_user 映射本地 → 本地 Redis 会话 → 登录成功
```

**同步**：
```
管理员 → 点「同步认证中心用户」 → POST /api/users/sync
  → list_users → GET /api/users?platform_id=（签名）
  → ① synced_users upsert ② users 表复制（is_active 合并）③ 删除多余（取消授权彻底删除）
  ← 同步统计消息
```

---

> 后续演进：多步登录（TOTP/验证码）UI 支持、强制改密（1010）前端流程、authPlatform 回调（资料变更后自动触发同步而非手动）。
