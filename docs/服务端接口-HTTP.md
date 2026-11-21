# 客户端 HTTP 接口

[返回总览](服务端接口文档.md) · [WebSocket](服务端接口-WebSocket.md) · [管理接口](服务端接口-管理.md)

以下路径相对于服务端根地址。所有接口依赖业务运行时，未启动统一 503，结构见总览。请求契约见 [types.py](../server/src/web/http/types.py)，路由见 [routes.py](../server/src/web/http/routes.py)。标注“必填”的字段必须传入；未列出的额外字段不会形成新功能。

## 1. 密码与令牌

### 1.1 `GET /auth/public_key`

无需业务令牌，无参数。返回 `{"public_key":"-----BEGIN PUBLIC KEY-----\n..."}`。

注册、登录、重置的密码必须使用此公钥加密：RSA 2048 位、OAEP、SHA-256，MGF1 也使用 SHA-256；加密结果 base64 编码为 JSON 字符串。不能直接提交密码明文、bcrypt 哈希或 PKCS#1 v1.5 密文。公钥随运行时生成，业务重启后应重新获取。

Python 加密示例（`password` 为用户输入；不要在日志中打印）：

```python
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def encrypt_password(public_key_pem: str, password: str) -> str:
    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    encrypted = key.encrypt(
        password.encode("utf-8"),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    return base64.b64encode(encrypted).decode("ascii")
```

来源：[account.py](../server/src/application/user/account.py)。RSA 加密长度受密钥和 OAEP 开销限制，不能把任意长文本作为密码直接加密。

### 1.2 两种用户令牌

| 字段 | 用途 | 生命周期 |
| --- | --- | --- |
| `login_token` | `POST /auth/auto_login` 的 `token` | 服务端保存的会话凭据；登录/自动登录成功时轮换 |
| `message_token` | 偏好、历史、动态、图片及 WebSocket `user_auth` | HS256 JWT，配置 `message_token_ttl_seconds`；安全默认 3600 秒，配置合法范围 60–86400 秒 |

`message_token` 包含 `user_uuid`、`iat`、`exp`、`jti`、`session_fp`，与当前会话凭据绑定。重新登录、自动登录轮换或重置账号，会使旧会话对应的消息令牌失效；不能只看 JWT 的 `exp` 判断是否仍然有效。业务使用时应保留登录响应中的最新一对令牌。

令牌所在位置：

| 请求 | 令牌位置 |
| --- | --- |
| `GET /history`、`GET /dynamics`、`GET /dynamics/unread`、`GET /dynamics/{dynamic_id}/comments` | `Authorization: Bearer <message_token>`，用户名仍在 query |
| 偏好、动态写入、图片接口 | JSON `token` 字段，值为 `message_token` |
| `POST /auth/auto_login` | JSON `token`，值为 `login_token` |
| WebSocket 认证 | `user_auth.payload.token`，值为 `message_token` |

用户业务 GET 的 Bearer 解析严格：缺失 401 `消息令牌缺失`；不符合 `Bearer <token>` 格式 401 `无效的 Authorization 请求头`。query 中传 `token` 不能替代请求头。

### 1.3 认证限流和公共错误

| 接口 | 次数/窗口 |
| --- | --- |
| `/auth/login`、`/auth/auto_login` | 10 次/60 秒 |
| `/auth/register` | 5 次/60 秒 |
| `/auth/reset_account` | 3 次/300 秒 |

按来源 IP 和归一化用户名/邀请码等 subject 分别限制，任一超限返回 429 `请求过于频繁，请稍后再试`；限流存储为进程内状态。密码认证并发工作槽满返回 503 `认证服务繁忙，请稍后再试`。RSA 解密失败返回 400 `Encryption error`。

来源：[rate_limits.py](../server/src/web/http/rate_limits.py)、[user_interface.py](../server/src/web/http/user_interface.py)、[credential_service.py](../server/src/infrastructure/persistence/database/services/credential_service.py)。

## 2. 账号

### 2.1 `POST /auth/register`

无需已有令牌。JSON：

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `username` | string | 必填，用户名 |
| `password` | string | 必填，RSA 密文 base64 |
| `invite_code` | string | 必填，尚未使用且未禁用的邀请码 |

```json
{"username":"alice","password":"<RSA密文base64>","invite_code":"<邀请码>"}
```

成功 `{"message":"注册成功","user_id":"alice"}`，不直接返回登录令牌；注册后仍需登录。邀请码被记为已使用并关联用户。邀请码无效、已使用、禁用、用户名冲突或注册存储失败返回 400 `注册失败，请检查邀请码或用户名`。

### 2.2 `POST /auth/login`

JSON 必填 `username:string`、`password:string`（RSA 密文）；可选 `request_token:boolean=false`。当前实现不读取 `request_token` 来决定是否发令牌，登录成功始终返回：

```json
{"login_token":"<新会话凭据>","message_token":"<JWT>","user_id":"alice"}
```

用户不存在、密码错误或认证失败：401 `用户名或密码错误`。当前实现还会把 JWT_SECRET 未配置导致的令牌生成失败映射到认证失败，排障时需同时检查服务端配置。

### 2.3 `POST /auth/auto_login`

JSON 必填 `username:string`、`token:string`（上次保存的 `login_token`）：

```json
{"username":"alice","token":"<login_token>"}
```

成功 `{"message":"登录成功","user_id":"alice","login_token":"<新凭据>","message_token":"<新JWT>"}`。必须用新值覆盖本地旧值；旧 `login_token` 不能继续复用。失败：401 `登录失败，自动登录验证未通过`。

### 2.4 `POST /auth/reset_account`

JSON 必填 `invite_code:string`、`new_username:string`、`new_password:string`（RSA 密文）。无需登录令牌；使用的是已经关联账号的**原邀请码**。

成功 `{"message":"重置成功","username":"new-name"}`。会修改关联账号用户名和密码、清除旧会话凭据；需要重新登录。

失败均为 400：`邀请码无效`、`邀请码已被禁用，无法重置`、`邀请码尚未被使用，无法重置`、`邀请码关联的用户不存在`、`新用户名已被其他用户使用`、`重置失败`，以及公共加密错误。

## 3. 模型类型与用户偏好

### 3.1 `GET /llm/client-model-types`

无需令牌，无参数。返回服务端配置的模型需求，客户端据此选择本地供应商/模型，再通过 WebSocket 声明可承担的类型：

```json
{
  "types": [{
    "id":"chat-model",
    "name":"对话模型",
    "description":"客户端需满足的能力说明",
    "model_kind":"llm",
    "requires_json":false,
    "requires_thinking":false
  }]
}
```

`model_kind` 为 `llm` 或 `vlm`；列表可为空，id/名称以实际响应为准，不是固定模型供应商列表。委托请求响应见 [WebSocket 文档](服务端接口-WebSocket.md)。

### 3.2 `POST /preference/get`

JSON 必填 `username:string`、`token:string`（消息令牌）。返回 `{"preferences":{...}}`，偏好对象字段由用户数据决定，没有固定完整 schema。

无效/过期/不匹配令牌：401 `消息令牌无效或已过期`；未找到用户：404 `未找到该用户`。

### 3.3 `POST /preference/overwrite`

JSON 必填 `username:string`、`token:string`、`preferences:object`：

```json
{"username":"alice","token":"<message_token>","preferences":{"relationship":"朋友"}}
```

这是整体覆盖，不是 PATCH。`relationship` 若提供必须是字符串，否则 422 `relationship 必须是字符串`。其他字段不因此自动获得业务含义。

成功 `{"status":"success","message":"Preferences overwritten successfully"}`。成功保存后会向该用户仍活跃的交互广播关系偏好刷新。token 无效 401；用户不存在/保存失败 404 `未找到该用户`。

## 4. 聊天历史

### `GET /history`

Header：`Authorization: Bearer <message_token>`。

| Query 字段 | 类型 | 默认/语义 |
| --- | --- | --- |
| `username` | string | 必填 |
| `count` | integer | 默认 10，业务层截到 1–200 |
| `end_index` | integer | 默认 -1，表示当前总条数；大于总数也按总数处理；正常分页请用 -1 或非负索引 |

```http
GET /history?username=alice&count=20&end_index=-1
Authorization: Bearer <message_token>
```

```json
{
  "history":[{
    "uuid":"<消息UUID>",
    "content":"你好",
    "source":"user",
    "timestamp":"2026-11-01 12:34:56",
    "type":"text"
  }],
  "start_index":0
}
```

以 `end_index` 为右侧不含边界，返回 `[max(0,end_index-count), end_index)` 的历史窗口，窗口内按时间升序。空结果 `{"history":[],"start_index":0}`。下一页更早消息传上一页 `start_index`；为 0 时不再向前翻。索引是历史位置，不是 UUID，也不是稳定的增量同步游标；没有 `total`、`has_more`、按 UUID 查询或按更新时间拉取接口。

条目字段：`uuid` 消息标识，`content` 文本或本地图片路径，`source` 消息来源（用户/角色来源值，以返回数据为准），`timestamp` 秒级无偏移时间，`type` 内容类型。图片历史会用 `meta_data.image_client_path` 作为 `content`，隐藏图片理解文本；路径可能缺失或属于其他设备，不能直接作为服务端 URL。应使用 UUID 调用 `/get_image`。

鉴权失败 401 `消息令牌无效或已过期`。来源：[user_conversation_helper.py](../server/src/application/user/user_conversation_helper.py)、[conversation_service.py](../server/src/infrastructure/persistence/database/services/conversation_service.py)。

## 5. 动态与评论数据对象

接口以 `item` 或 `items` 包装下列对象。状态字段是业务处理状态，客户端不要把 `memory_status` 或 `reply_status` 当作 HTTP 请求完成标志。

### 5.1 DynamicPost

| 字段 | 类型/用途 |
| --- | --- |
| `id` | string，动态 ID |
| `author_type` | string，`user` / `agent` / `system` |
| `author_id`、`author_name` | 作者标识/显示名 |
| `owner_user_id` | 所属用户 UUID；全局系统动态可为空 |
| `visibility` | `private` / `global` |
| `content` | 文本内容 |
| `image_refs` | 图片引用数组；当前用户发布接口不接收此字段 |
| `source_type`、`source_id` | 来源类型及来源关联 ID，ID 可空 |
| `allow_comment` | boolean，是否允许评论 |
| `memory_policy`、`memory_status`、`memory_error` | 记忆接纳策略、状态、可空错误 |
| `reply_status`、`reply_error` | 后台互动状态、可空错误 |
| `status` | 发布状态，用户列表仅取 `published` |
| `created_at`、`updated_at` | `YYYY-MM-DD HH:mm:ss` |
| `comment_count` | 评论数 |
| `cursor` | 当前项游标，用于分页 |

### 5.2 DynamicComment

字段为 `id`、`dynamic_id`、`author_type`、`author_id`、`author_name`、`owner_user_id`、`parent_comment_id`（可空）、`content`、`memory_policy`、`memory_status`、`memory_error`、`reply_status`、`reply_error`、`status`、`created_at`、`updated_at`、`cursor`。

评论没有动态的 `visibility`、`image_refs`、`allow_comment`、`comment_count` 字段。数据对象来源：[dynamic_store.py](../server/src/infrastructure/persistence/database/services/dynamic_store.py)。

## 6. 动态接口

### 6.1 `GET /dynamics`

Bearer 鉴权；query：`username:string` 必填，`limit:integer=20`（截到 1–100），`cursor:string|null` 可选。

返回 `{"items":[<DynamicPost>],"has_more":false,"next_cursor":null}`。只取已发布且全局可见或属于当前用户的动态，按 `created_at DESC, id DESC`。要翻向更早动态，把 `next_cursor` 原样传入下一请求。

游标内部格式是 `datetime.isoformat()|id`，客户端应当作不透明字符串并 URL 编码。格式无效时当前实现静默忽略，可能重新返回第一页，不会报参数错误。

### 6.2 `POST /dynamics`

JSON 必填 `username:string`、`token:string`、`content:string`。内容去首尾空白，不可为空。

成功 `{"item":<DynamicPost>}`。强制使用当前认证用户作为作者和 owner、`visibility="private"`、`source_type="user_post"`、`allow_comment=true`、`memory_policy="candidate"`。不能用额外 JSON 字段发布全局动态、伪造作者或附带图片。

空内容 400 `动态内容不能为空`；创建失败 400 `动态创建失败` 等业务错误；token 无效 401。

### 6.3 `GET /dynamics/unread`

Bearer 鉴权，query 必填 `username:string`。返回：

```json
{
  "has_unread":false,
  "unread_count":0,
  "unread_dynamic_count":0,
  "unread_comment_count":0,
  "last_read_dynamic_at":null,
  "last_read_comment_at":null
}
```

统计当前用户可见的非用户作者动态，以及该用户所属评论流中的非用户作者评论。不是所有动态总数。首次请求会创建已读状态；两个时间非空时使用秒级本地时间格式。

### 6.4 `POST /dynamics/read`

JSON 必填 `username:string`、`token:string`。返回 `{"ok":true,"last_read_dynamic_at":"2026-11-01 12:34:56","last_read_comment_at":"2026-11-01 12:34:56"}`。

动态和评论同时按当前服务端本地时间全部标为已读，没有逐条或指定时间标记功能。存储失败 400 `标记已读失败`；token 无效 401。

### 6.5 `GET /dynamics/{dynamic_id}/comments`

Path：`dynamic_id:string`；Bearer 鉴权；query 必填 `username:string`，可选 `limit:integer=100`（截到 1–200）、`cursor:string|null`。

返回 `{"items":[<DynamicComment>],"has_more":false,"next_cursor":null}`。按 `created_at ASC, id ASC`，游标向更晚评论推进。只返回当前用户 owner 下的已发布评论；即使动态为全局，也不是所有用户评论的公共聚合。

动态不存在或不可见：404 `动态不存在或无权访问`；token 无效 401。游标格式与无效处理同动态列表。

### 6.6 `POST /dynamics/{dynamic_id}/comments`

JSON 必填 `username:string`、`token:string`、`content:string`；可选 `parent_comment_id:string|null=null`。作者及 owner 固定为当前用户，记忆策略为 `candidate`。

成功 `{"item":<DynamicComment>}`。父评论必须属于同一动态及同一 owner。空评论、动态不存在/不可见、禁止评论、父评论无效或存储失败返回 400（如 `评论内容不能为空`、`评论创建失败`）；token 无效 401。当前没有用户删除/编辑动态或评论的公开接口。

## 7. 图片

### 7.1 `POST /get_image`

JSON 必填 `username:string`、`token:string`、`uuid:string`（历史图片消息 UUID）。可选 `image_client_path` 在读取接口中不使用。

成功是**图片二进制流**，不是 JSON 或 base64。`Content-Type` 来自已验证永久媒体的 MIME。按当前用户自己的 `type="image"` 历史记录定位媒体，再核验 owner；不能用其他用户消息的 UUID 下载图片。

兼容旧数据：无永久 `media_id` 时使用历史 metadata 的 `image_server_path` 读取文件；`.jpg/.jpeg` 返回 `image/jpeg`，`.gif` 为 `image/gif`，其他默认为 `image/png`。

失败：401 消息令牌错误；400 `获取图片失败，图片不存在或无权限访问`、`文件不存在`、`获取图片失败，读取文件出错` 等。客户端先检查状态和 Content-Type，避免把 JSON 错误当图片。

### 7.2 `POST /update_image_client_path`

JSON 必填 `username:string`、`token:string`、`uuid:string`，并应传 `image_client_path:string`（该设备的缓存路径）：

```json
{"username":"alice","token":"<message_token>","uuid":"<图片消息UUID>","image_client_path":"C:/cache/picture.png"}
```

成功 `{"message":"更新成功"}`。仅更新当前用户 image 历史记录的 metadata，不上传文件、不修改服务端图片内容。schema 对该路径默认值为 `None`，但不是规范设计的删除接口，客户端应明确传字符串。

401 消息令牌错误；400 `更新失败，记录不存在或无权限访问`。路径没有额外内容校验，并保存在服务端历史 metadata 中，不具备每设备独立路径命名空间；另一设备读取历史时须自行判断路径是否可用。

图片发送通过 WebSocket `user_image`，见 [图片输入契约](服务端接口-WebSocket.md#4-业务输入)。
