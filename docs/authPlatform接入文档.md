# authPlatform 平台接入接口文档

> 面向**接入平台**（如 ops-platform）的对接说明。authPlatform 是统一鉴权中心：
> 账号/密码/授权/token 由 authPlatform 管理，各平台只做**转发调用**，本地不存账号密码。
>
> 更新：2026-08-06 ｜ 与源码 `api/` 目录一一对应，如需核对实现可直接看对应文件。

---

## 1. 接入准备

1. 管理员在 authPlatform 管理后台「平台管理」注册你的平台，得到：
   - `platform_id`（如 `ops-platform`）
   - `secret`（**独立加密盐，仅创建时展示一次**，务必保存；用于请求签名）
   - 可选配置：IP 白名单、平台自定义登录方式 `login_methods`
2. 在「授权管理」给目标用户勾选你的平台（未授权用户无法登录、也拉取不到）。
3. 调用前自检：`GET /api/health` 返回 `{"code":0,...}` 即服务正常。

---

## 2. 请求签名（所有平台侧接口必需）

每个请求需携带 3 个头，防伪造 + 防重放：

```
X-Platform-Id: <platform_id>
X-Timestamp:   <当前 unix 秒>
X-Sign:        <签名 hex>

sign = HMAC-SHA256(
    secret,
    method + "|" + 完整RequestURI + "|" + timestamp + "|" + sha256(body)hex
)
```

要点：
- `完整RequestURI` = 路径 + 查询串**原样**（如 `/api/users?platform_id=ops-platform`），防 query 篡改绕过授权。
- `body` = 请求体原始字节；GET 无 body 时 `sha256("")`。
- 时间戳允许 ±300 秒，超出返回 `1001`。

**Python 签名函数（可直接复用）**：

```python
import hashlib, hmac, time, json, urllib.request

SECRET = "你的平台secret"
BASE   = "http://127.0.0.1:8080"
PID    = "ops-platform"

def signed_request(method, path, body=None):
    body_bytes = (body if isinstance(body, bytes) else json.dumps(body or {}).encode()) if body is not None else b""
    ts = str(int(time.time()))
    msg = f"{method}|{path}|{ts}|{hashlib.sha256(body_bytes).hexdigest()}"
    sign = hmac.new(SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(BASE + path, data=body_bytes, method=method)
    req.add_header("X-Platform-Id", PID)
    req.add_header("X-Timestamp", ts)
    req.add_header("X-Sign", sign)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# 示例
r = signed_request("POST", "/api/auth/verify",
    {"method": "username_password", "identifier": "alice", "credential": "alice1234"})
print(r)
```

---

## 3. 统一响应与错误码

所有接口返回 HTTP 200 + JSON：

```json
{"code": 0, "msg": "ok", "data": {...}}
```

| code | 含义 | 处理建议 |
|---|---|---|
| 0 | 成功 | — |
| 1001 | 平台签名无效 / 时间戳过期 | 检查 secret、时间戳、RequestURI 是否与请求一致 |
| 1002 | 平台不存在或已停用 | 检查 platform_id |
| 1003 | 账号或密码错误（或验证码错误） | 提示用户 |
| 1004 | 账号已禁用 | 提示联系管理员 |
| 1005 | 登录尝试过多 / 账号被临时锁定 | 提示稍后再试（5 次失败锁 15 分钟） |
| 1006 | 该用户未授权登录此平台 | 提示联系管理员授权 |
| 1007 | 参数错误 / 登录票据无效或已过期 | 检查请求体 |
| 1009 | IP 不在白名单 | 检查来源 IP（后台配置） |
| 2001 | 内部错误 | 反馈管理员看服务日志 |

---

## 4. 接口明细

### 4.1 登录校验 `POST /api/auth/verify`

登录**第一步**（或唯一一步）。请求体：

```json
{
  "platform_id": "ops-platform",
  "method": "username_password",
  "identifier": "alice",
  "credential": "alice1234"
}
```

- `method` 可选值：`username_password`（identifier=用户名）、`email_password`（identifier=邮箱）、`phone_code`（identifier=手机号，配合 send-code）、`username_totp`（identifier=用户名 + TOTP 动态码，**无密码登录**，可单独或作第二因子）。
- **验证模式**（平台配置 `auth_mode`）决定 `method` 的匹配规则：
  - `two_step`（二次验证，默认）：`method` 必须等于配置列表的**第一个**；配置 ≥2 种方式时走多步（第一步过 → ticket → 后续步骤）。
  - `single`（单次登录）：`method` 可以是配置列表**任意一种**，通过即直接发 token（不走多步）。
- `username_totp` 可单独配置（用户名+TOTP 免密单步），也可在 `two_step` 中作为**第二因子**（如 密码 → 用户名+TOTP）；用户须先绑定 TOTP（平台侧 `POST /api/auth/totp/save` 上报密钥）才能使用，未绑定返回 1003「该用户未启用 TOTP 双因子验证」。
- CMDB 用户迁移（无密码、仅双因子登录）：查询/插入 SQL 见 `doc/MIGRATION.md`。

**响应 A — 单步完成（single 模式任一通过，或 two_step 只配置 1 种方式）：**

```json
{"code":0,"data":{
  "token": "<64位hex不透明token>",
  "expires_at": "2026-08-07T10:00:00+08:00",
  "user": {"uid":"u_xxx","username":"alice","nickname":"爱丽丝","status":1}
}}
```

**响应 B — 多步骤（`auth_mode=two_step` 且配置 ≥2 种方式）：**

```json
{"code":0,"data":{
  "ticket":"<5分钟内有效的登录票据>","step":1,"total_steps":2,
  "next_method":"username_totp","expires_in":300,
  "identifier":""}}
```

→ 继续调 §4.2，直到 `total_steps` 走完拿到 token。

### 4.2 登录后续步骤 `POST /api/auth/verify-step`

```json
{"platform_id":"ops-platform","ticket":"<上一步返回>","credential":"<当前步骤的凭证>"}
```

- 请求体**不含 method**：下一步方式由 ticket 关联的登录流程自动推进（`next_method` 提示）。
- `credential`：`username_totp` 步传 6 位 TOTP 动态码；`phone_code` 步传手机验证码。
- 未走完返回下一个 `next_method`；**最后一步通过后**返回与响应 A 相同的 `token`。
- ticket 一次性、5 分钟有效；凭证失败**不销毁** ticket 可重试（受限流保护）。

### 4.3 发送验证码 `POST /api/auth/send-code`

```json
{"platform_id":"ops-platform","method":"phone_code","identifier":"13800000000"}
```

- `method`：`phone_code`（手机号+短信验证码；`email_code` 已移除）。
- **开发模式**：未接真实短信/邮件服务商，验证码直接返回，便于联调：
  ```json
  {"code":0,"data":{"dev_code":"482913","expires_in_seconds":300,"method":"phone_code"}}
  ```
  接入真实发送器后 `dev_code` 字段会移除，改为平台自行从短信/邮箱获取验证码。

### 4.4 修改密码 `POST /api/auth/change-password`

```json
{"platform_id":"ops-platform","username":"alice","old_password":"旧密码","new_password":"新密码"}
```

- 校验旧密码 + 授权 + 密码策略（≥8 位含字母数字）。
- 返回 `{"code":0}`。

### 4.5 修改资料 `POST /api/auth/update-profile`

```json
{
  "platform_id": "ops-platform",
  "username": "alice",
  "nickname": "爱丽丝",
  "email": "alice@example.com",
  "phone": "13800000000",
  "password": "new_password_123",
  "totp_secret": ""
}
```

- 约定：**变更逻辑在平台处理、数据在认证中心存储**——平台把变更后的字段一次性提交，本接口只负责授权校验与落库。
- 字段规则：
  - `nickname`：非空才更新。
  - `email` / `phone`：**不传=不修改**；`""`=清空（存 NULL，不参与唯一约束）；非空=更新（唯一冲突预检查，已被其他账号使用会报错）。
  - `password`：非空则代改密码（管理员场景，无需旧密码），authPlatform 哈希存储（校验密码策略）。
  - `totp_secret`：**不传=不修改**；非空 base32 密钥=重新绑定并启用 TOTP；`""`=清除（解除双因子）。
- 返回该用户白名单信息（uid/username/nickname/phone/email/status/created_at）。

### 4.6 上报双因子密钥 `POST /api/auth/totp/save`

```json
{"platform_id":"ops-platform","username":"alice","secret":"JBSWY3DPEHPK3PXP"}
```

- **绑定流程在平台侧完成**（生成密钥/扫码/验证码确认），绑定成功后把 base32 格式 secret 上报，authPlatform 仅存储；后续登录的 TOTP 校验由 authPlatform 统一完成（见 §4.2 `username_totp` 步）。
- 重新绑定/解除亦可走 §4.5 `update-profile` 的 `totp_secret` 字段（非空=绑定，`""`=清除）。
- 返回 `{"code":0,"data":{"totp_enabled":true}}`。

### 4.7 拉取单个用户 `GET /api/users/{uid}?platform_id=ops-platform`

- 仅返回**授权给本平台**的用户；不存在、未授权或**认证中心管理员（is_admin）**一律 HTTP 404（平台侧不可见）。
- 字段白名单：`uid / username / nickname / phone / email / status / created_at`（**绝不包含密码等凭据**）。

### 4.8 拉取用户列表 `GET /api/users?platform_id=ops-platform&keyword=可选`

- 返回本平台**已授权**的用户列表（服务端强制过滤；**认证中心管理员不返回**，不同步到任何平台）：
  ```json
  {"code":0,"data":{"users":[{"uid":"u_xxx","username":"alice","nickname":"爱丽丝","phone":"13800000000","email":"alice@example.com","status":1,"created_at":"..."}]}}
  ```

---

### 4.9 管理后台接口（控制台使用，需登录态 `Authorization: Bearer <token>`）

> 登录：`POST /api/admin/login {username, password}` → `{token, user}`；登录成功后后续请求携带 `Authorization: Bearer <token>`。
> **超级管理员（is_admin=1）不出现在用户列表与授权矩阵中**，其个人信息（如修改密码）通过个人设置完成，由平台侧按需调用 `POST /api/admin/me/password {old_password, new_password}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/admin/me` | 当前登录管理员信息 |
| POST | `/api/admin/me/password` | 修改自己的密码（校验原密码） |
| GET | `/api/admin/users?keyword=&category=&status=&totp=&has_category=` | 用户列表（不含超管；keyword 关键字、category 精确分类、status 1/0、totp 1/0、has_category 1=已分类 0=未分类，可组合） |
| POST | `/api/admin/users` | 创建用户 `{username, password, nickname, phone, email, category}` |
| PUT | `/api/admin/users/{id}` | 更新 `{nickname, phone, email, status, category}` |
| DELETE | `/api/admin/users/{id}` | 删除用户 |
| POST | `/api/admin/users/{id}/reset-password` | 重置密码：不传 `new_password` 时**自动生成**符合密码策略的随机密码并一次性返回 `{password}`；传 `new_password` 则按策略校验后更新 |
| POST | `/api/admin/users/batch-category` | 批量设置用户分类 `{user_ids: [1,2], category: "开发"}`（category 空串=清除分类） |
| GET | `/api/admin/grants?category=` | 授权矩阵数据（用户×平台，不含超管，支持分类筛选） |
| POST | `/api/admin/users/{id}/grants` | 全量设置用户可登录平台 `{platform_ids: [1,2]}` |
| POST | `/api/admin/platforms/{id}/grants` | 列级批量授权 `{action: "grant"\|"revoke", user_ids: [...]}`（只增/只删指定用户，不影响其他用户授权） |
| GET/PUT | `/api/admin/platforms`、`/api/admin/platforms/{id}` | 平台管理（创建时返回一次明文 secret） |
| POST | `/api/admin/platforms/{id}/rotate-secret` | 密钥轮换（双盐过渡，第二次轮换吊销旧盐） |
| GET | `/api/admin/logs?username=&platform_id=&success=&limit=` | 审计日志 |
| GET/PUT | `/api/admin/settings`、`/api/admin/settings/{key}` | 系统设置（含 `user_categories` 用户分类列表 `{items:[...]}`） |

**用户分类**：分类（开发/测试/运营/风控/数分等）由管理员在系统设置维护（可自定义增删），用于用户管理标识、多选批量分类与授权管理按分类筛选（快捷授权）；分类归属是认证中心存储的用户属性，权限/部门/角色等业务数据仍由各平台自行维护。

---

## 5. 登录流程示例（完整可跑）

```python
# 单步登录（默认配置：username_password）
r = signed_request("POST", "/api/auth/verify",
    {"method": "username_password", "identifier": "alice", "credential": "alice1234"})
if r["code"] == 0 and "token" in r["data"]:
    token = r["data"]["token"]          # 平台自行保存 token，自行管理生命周期（不吊销）
else:
    print("登录失败:", r["msg"])

# 无密码登录：用户名 + TOTP 动态码（平台配置 login_methods=["username_totp"]）
r = signed_request("POST", "/api/auth/verify",
    {"method": "username_totp", "identifier": "alice", "credential": "6 位动态码"})
# -> code=0 发 token；未绑定 TOTP 返回 1003「该用户未启用 TOTP 双因子验证」

# 两步登录（username_password + username_totp）
r1 = signed_request("POST", "/api/auth/verify",
    {"method": "username_password", "identifier": "alice", "credential": "alice1234"})
ticket = r1["data"]["ticket"]
# 用户输入 Authenticator 上的 6 位验证码
code = input("TOTP code: ")
r2 = signed_request("POST", "/api/auth/verify-step",
    {"ticket": ticket, "credential": code})
# r2["data"]["token"] 即最终 token
```

---

## 6. 常见问题

| 现象 | 原因/排查 |
|---|---|
| `1001` 签名无效 | secret 是否写对；RequestURI 是否**含 query 原样**；时间戳偏差 >300s |
| `1006` 未授权 | 管理员未在「授权管理」给该用户勾选你的平台 |
| 拉取用户 404 | 该用户未授权你的平台（或不存在）——对平台完全不可见 |
| `1005` 锁定 | 该账号 5 次失败已锁 15 分钟（账号维度，全平台共享） |

> 审计：每次登录成功/失败都会写入 authPlatform 审计日志（管理后台「审计日志」页可查，含 reason：ok/bad_cred/bad_code/bad_totp/unauthorized/locked/banned/disabled）。

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

> 后续演进：多步登录（TOTP/验证码）UI 支持、authPlatform 回调（资料变更后自动触发同步而非手动）。
