# TODO.md 分析与修改建议

> 基于代码仓库实际状态（commit a790f30）对每个 TODO 项的完成度分析和具体修改方案。
> 分析时间：2026-05-09

---

## 总体状态

| # | TODO 项 | 状态 | 优先级 |
|---|---------|------|--------|
| 1 | 好感度系统弃用 | **部分完成** | 高 |
| 2 | 表达风格偏好 | **部分完成** | 中 |
| 3 | 新客户端接口 | **未开始** | 中 |
| 4 | 日程逻辑/事件系统 | **部分完成** | 低（现有方案可用）|
| 5 | 结构化记忆组织 | **未开始** | 低（设计较复杂）|
| 6 | 更天真活泼人设 | **阻塞（文件缺失）** | **最高（会崩溃）** |

---

## 6. 更天真活泼人设（阻塞问题，需优先处理）

### 现状

TODO 中写"我写好了新的prompt，暂时不需要进一步修改"，但关键文件在磁盘上**不存在**：

- `server/res/agent/persona/luotianyi_persona.json` — **不存在**（config.json 第73行配置）
- `server/res/agent/prompts/` 目录 — **不存在**（config.json 第48行配置）

`main_chat.py:202-243` 的 `_init_static_variables_sync()` 中，如果 persona 文件缺失：
1. 第210行 warning 日志后会 return
2. 第241-243行的 assert 会触发 `AttributeError` → **应用启动崩溃**

同样，`prompt_manager.py` 在模板目录不存在时也会报错。

### 修改建议

**需要创建以下文件：**

#### a) `server/res/agent/persona/luotianyi_persona.json`

必须包含三个字段：
```json
{
  "character_name": "洛天依",
  "character_persona": "...（天真活泼的人设描述）",
  "speaking_style": "...（口语化的说话风格描述）"
}
```

可以参考现有代码中对 `main_chat.py:221-239` 的解析逻辑：`character_persona` 可以是字符串或字符串数组，`speaking_style` 可以是字符串或数组。

**注意：** config.json 第221行 `citywalk.decision.persona_path` 也引用了同一个文件，修改时需确保兼容。

#### b) `server/res/agent/prompts/` 目录及模板文件

配置中引用的 prompt 模板名称（共约8个）：

| 配置路径 | prompt_name | 用途 |
|---------|-------------|------|
| `main_chat.llm_module` | `topic_reply_prompt` | 话题回复生成（核心） |
| `topic_extractor.llm_module` | `topic_extraction_prompt` | 话题提取 |
| `conversation_manager.llm_module` | `summary_prompt` | 对话摘要 |
| `memory_manager.memory_writer` | `memory_write_prompt` | 记忆提取写入 |
| `memory_manager.memory_searcher` | `memory_search_prompt` | 记忆检索查询生成 |
| `memory_manager.user_profile` | `user_profile_update_prompt` | 用户画像更新 |
| `vision_module.vlm_module` | `vision_interaction_prompt` | 图片描述 |
| `activity_maker` | `return_login_activity_prompt` / `user_silence_activity_prompt` | 主动活动 |

需要确认 `PromptManager` 的预期模板格式（Jinja2模板），然后创建对应文件。

### 建议执行的修改

1. 先确认 prompt 模板是 Jinja2 格式还是 JSON 格式，检查 `PromptManager` 的代码
2. 创建 `server/res/agent/persona/luotianyi_persona.json`
3. 创建 `server/res/agent/prompts/` 目录和所需的模板文件
4. 如果 prompt 内容已写在别处（如设计文档），直接迁移进来

---

## 1. 好感度系统弃用（部分完成）

### 现状

- Pydide 客户端中已无好感度相关代码 ✅
- 服务端 pipeline 模块中无好感度注册 ✅
- 但服务端 `luotianyi_agent.py` 中好感度代码**仍在活跃运行**：
  - 第321-327行：好感度上下文注入 `user_description`
  - 第557-572行：`add_conversation()` 中调用 LLM 分析并更新好感度
- 移动端 app (`app/app/index.tsx` 第187-191行) 仍有好感度显示 ✅
- `affection_manager.py` 完整保留（197行）
- `sql_database.py` 中 `affection_score` / `affection_total_gained` 字段和 `AffectionLog` 表

### 修改方案

```
修改步骤：
1. luotianyi_agent.py
   └─ 删除第557-572行好感度分析代码（add_conversation中的affection调用）
   └─ 删除第321-327行好感度上下文注入代码
   └─ 删除第22行 AffectionManager 导入
   └─ 删除第99-102行 affection_manager 初始化
   └─ 如果其他地方无引用，清理

2. app/
   └─ 删除 app/utils/getAffection.ts
   └─ 删除 app/app/index.tsx 中的 affectionBadge 相关 JSX（第187-191行）

3. 数据库
   └─ sql_database.py：保留字段和表（TODO 说保留代码，ORM字段不删影响不大）
   └─ 或添加 `ignore` 标记列（可选）

4. 清理可选：
   └─ server_main.py：检查有无注册好感度路由
   └─ 移除 affection_manager.py（TODO 说保留代码，可以不删）
```

---

## 2. 表达风格偏好（部分完成）

### 现状

- 用户偏好设置（关系类型、表达风格、性格特点）已在客户端实现 ✅
  - `preferences_dialog.py` 有"相处模式"选项卡
  - `user_preferences_manager.py` 管理本地持久化
  - WebSocket 同步到服务端 `server_main.py:154-170`
- 服务端保存到 `User.preferences` 字段 ✅
- **但注入方式不符合 TODO 要求**：
  - 当前：`user_description + "\n" + pref_context`（`luotianyi_agent.py:318`）
  - 要求：在 prompt 中增加**专门的部分**注入表达风格偏好
- **首引导步骤未实现**：注册时没有让用户选择偏好

### 修改方案

```
修改步骤：
1. main_chat.py — 修改 prompt 注入方式
   └─ 在 _build_user_persona() 或 generate_response() 中，
       增加一个独立的参数（例如 user_preferences）
   └─ 相应地修改 topic_reply_prompt 模板，加入类似
      {{ user_preferences }} 的变量

2. luotianyi_agent.py
   └─ generate_topic_reply_for_pipeline() 中：
      - 将偏好信息从 user_description 中分离
      - 通过新的参数传递到 main_chat

3. client/src/gui/login_dialog.py — 添加引导步骤
   └─ 注册成功后，弹出偏好选择界面
   └─ 包含关系类型下拉、表达风格下拉
   └─ 添加"先试试看（跳过）"按钮

4. 可选：app/ 移动端同样实现注册引导
```

---

## 3. 新的客户端接口（未开始）

### 现状

- 服务端 `account.py` 中**没有**重置密码/用户名的 API
  - 有 `register_user()`、`verify_user()`、token 管理
  - 没有 `reset_account_by_invite()` 或类似函数
- 客户端 `login_dialog.py` 中有登录/注册 tab
  - 注册已有邀请码输入框
  - 但没有"重置用户名和密码"功能
- 客户端无服务器地址配置界面
  - 地址从 `client/config/config.json` 读取
  - 启动时从配置文件解析 `server_url`

### 修改方案

```
服务端修改：
1. server_main.py — 增加重置路由
   └─ POST /auth/reset_account
   └─ 请求体：invite_code, new_username, new_password, confirm_password

2. account.py — 添加 reset_account 函数
   └─ 校验邀请码是否已被使用
   └─ 查找邀请码关联的旧用户（或允许指定新用户）
   └─ 覆写用户名和密码
   └─ 清除旧 auth_token

客户端修改（client/src/gui/login_dialog.py）：
3. 在登录/注册 tab 外增加"重置账号"按钮
   └─ 点击后展开输入框：邀请码、新用户名、新密码、确认新密码
   └─ 调用新的 POST /auth/reset_account 接口
   └─ 成功后提示并回到登录界面

4. 增加"服务器设置"按钮
   └─ 弹出对话框让用户输入服务器地址
   └─ 尝试获取 /auth/public_key 验证服务器可用性
   └─ 成功后写入 client/config/config.json
   └─ 失败则显示"服务器地址无效"
   └─ 需要修改 client/src/network/ 中的连接逻辑以支持动态地址
```

---

## 4. 日程逻辑/事件系统（部分完成）

### 现状

- `plugins/schedule/` 已有一个完整的日程模块 ✅
  - `schedule_manager.py`：独立线程运行，定时抓取 B站动态
  - `event_store.py`：JSON 文件持久化
  - `event_models.py`：6 种事件类型、4 种状态
  - `official_feed_fetcher.py`：B站 API 抓取
  - `event_parser.py`：LLM 解析动态为事件
  - `reminder_dispatcher.py`：提醒在线用户
  - `activity_context_provider.py`：事件上下文注入
- 但 TODO 要求的**统一事件数据库**未实现：
  - 没有 `ImportantDate` 数据表
  - 用户生日、纪念日存在客户端 JSON 中
  - 没有农历转换
  - 没有周期性事件的概念
  - 没有完整的触发条件系统
- 演唱会静默（silence period）在 `event_store.py:136-143` 有骨架

### 修改方案

```
整体来看，现有 schedule 模块已能满足核心需求（B站动态/演唱会），
TODO 的设计更全面但复杂度高。建议：

阶段一（短期，低工作量）：
1. 在 sql_database.py 中创建 ImportantDate 表
   └─ 字段：id, user_id, name, type, date, is_lunar, is_recurring, description
2. 将 ingress.py 中检测到的日期存入 DB 而非仅通知前端
3. 将节假日预写入 DB

阶段二（中期）：
4. 将 event_store.py 从 JSON 迁移到 SQLite DB
5. 实现农历到公历转换
6. 实现生日/纪念日登录触发提醒

阶段三（长期，按 TODO 设计）：
7. 完整的触发条件系统
8. 事件向对话注入的精细化控制
```

---

## 5. 结构化记忆组织（未开始）

### 现状

当前记忆系统：
- ChromaDB 向量存储 + BAAI/bge-large-zh-v1.5 嵌入
- LLM 驱动的记忆提取（`memory_write.py`），生成 `user_memory` / `event_memory` 两类
- LLM 驱动的记忆检索查询生成（`memory_search.py`）
- 每轮对话后写入，单条文本 → 单一向量
- 有去重机制（相似度阈值）

TODO 要求的三个改造均未实现：
1. **键值对 + 多 key**：当前每条记忆只有一个 content 文本
2. **Auto dreamer 记忆总结**：没有凌晨批处理
3. **上下文 memory pool**：没有维护最近的记忆列表

### 修改方案

```
这是一个较大的重构，建议分三步实施：

第一步：Memory Pool（短期，独立可实施）
1. chat_stream.py 增加 memory_pool 字段（List[str]）
2. topic_planner/topic_replier 传递 memory_pool
3. memory_search.py 在生成查询时参考 memory_pool，避免重复查询
4. memory_write.py 在写入时将新记忆加入 pool，超出容量丢弃最旧的

第二步：多 Key 存储
1. 修改 memory_write.py 的 _extract_knowledge，让 LLM 同时生成
   {"key": [...多个key...], "value": "..."} 结构
2. memory_write.py _has_similar_user_memory 改用 key 匹配
3. 迁移脚本：遍历旧记忆，对每条调用 LLM 生成多 key
   → 可以离线异步做，不阻塞用户体验

第三步：Auto Dreamer（难度最大，最后做）
1. 在 daily_scheduler.py 中增加凌晨任务
2. 读取前一日的所有记忆
3. LLM 聚类，生成事件总结
4. 将事件总结写回向量库
```

---

## 需要优先处理的问题总结（按紧急度排序）

1. **⚡ 紧急：创建 persona 文件和 prompt 模板** — 现有代码会崩溃
   - 创建 `server/res/agent/persona/luotianyi_persona.json`
   - 创建 `server/res/agent/prompts/` 及所有模板文件
   - 需要先确认 PromptManager 的模板格式规范

2. **高优先级：好感度系统清理** — 约 30 分钟
   - 删除 `luotianyi_agent.py` 中 3 处好感度代码
   - 清理移动端好感度显示
   - 约改动 4 个文件

3. **中优先级：表达风格偏好注入改造** — 约 1 小时
   - 修改 prompt 传递方式 + 客户端注册引导

4. **中优先级：客户端接口增强** — 约 2 小时
   - 服务端重置 API + 客户端 UI

5. **低优先级：事件系统、记忆重构** — 数天
   - 设计复杂，建议待基础功能稳定后再开始
