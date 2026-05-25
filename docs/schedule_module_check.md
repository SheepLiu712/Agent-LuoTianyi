# Schedule 模块架构与代码审查报告

**审查日期**：2026-05-25  
**审查范围**：`server/src/plugins/schedule/` 及相关调用链  
**审查人**：GitHub Copilot（自动化审查）

---

## 一、模块结构总览

```
server/src/plugins/schedule/
├── __init__.py                    # 包导出
├── event_models.py                # 数据模型、触发条件定义、类型转换
├── event_store.py                 # 基于 SQL 的事件存储层（CRUD + 节假日初始化）
├── event_parser.py                # 从 B站动态提取事件（VLM/LLM + 规则降级）
├── official_feed_fetcher.py       # B站/微博官方动态爬取器
├── schedule_manager.py            # 核心调度器（线程模型 + 静默判断 + 上下文提供）
├── reminder_dispatcher.py         # 提醒派发器（推送提醒到在线用户 ChatStream）
├── activity_context_provider.py   # 活动上下文注入对话（带 per-user 提及频率控制）
└── cookie_manager.py              # B站 Cookie 自动刷新（Playwright 无头浏览器）

关联调用方：
├── server_main.py                 # startup_event 启动 ScheduleManager → DailyScheduler
├── src/pipeline/topic_replier.py  # 每个话题生成时调用 get_active_context 注入活动
├── src/agent/activity_maker.py    # 静默期检查（is_silence_period）+ 重要日期查询
├── src/agent/date_processor.py    # 用户重要日期检测 → 写入 Event 表
└── src/plugins/daily_scheduler.py # 凌晨调度：citywalk/new_song 事件写入 EventStore
```

---

## 二、架构与功能问题

### 2.1 日程写入途径总结

| 写入途径 | 调用链 | 状态 |
|---------|--------|------|
| 用户重要日期 | `TopicReplier._process_date_detection()` → `DateDetector.detect()` → `process_detected_date()` → `_save_user_date_event()` 直接操作 DB | ⚠️ **有问题** |
| 中国假日 | `ScheduleManager._async_main()` → `EventStore.ensure_holidays()` → `add_event()` | ✅ 已修复 |
| B站动态提取 | `ScheduleManager._fetch_and_process()` → `OfficialFeedFetcher.fetch_all_new()` → `EventParser.parse_dynamics()` → `add_event()` | ✅ |
| 洛天依旅游 | `DailyScheduler._write_citywalk_event()` → `ScheduleManager.event_store.add_event()` | ✅ |
| 洛天依学歌 | `DailyScheduler._write_new_song_event()` → `ScheduleManager.event_store.add_event()` | ✅ |

### 2.2 发现的问题与修复

#### 问题 1：`_save_user_date_event` 绕过 EventStore API（已修复）

**严重性**：中等

**描述**：`server/src/agent/date_processor.py` 中的 `_save_user_date_event()` 直接操作 SQLAlchemy Session 写入 Event 表，绕过了 `EventStore.add_event()` 的重复检查和标准化流程。

**修复**：添加了 `id=str(uuid4())` 确保 Event 的 id 字段不为空（SQLite 不会自动生成 UUID），确保与 EventStore 写入格式一致。

**文件**：`server/src/agent/date_processor.py`

---

#### 问题 2：`ensure_holidays` 农历节日去重使用错误的 date_mmdd（已修复）

**严重性**：高

**描述**：在 `EventStore.ensure_holidays()` 中，农历节日查询已存在事件时使用公历日期 `f"{sol_month:02d}-{sol_day:02d}"` 进行匹配，但实际存入的是农历日期 `f"{l_month:02d}-{l_day:02d}"`。这导致农历节日的去重逻辑完全无效，每次启动都会重复创建。

**修复**：将查询匹配从 `f"{sol_month:02d}-{sol_day:02d}"` 改为 `f"{l_month:02d}-{l_day:02d}"`。

**文件**：`server/src/plugins/schedule/event_store.py`

---

#### 问题 3：`check_trigger_condition` 缺失 `1_hour_before` 条件（已修复）

**严重性**：高

**描述**：`TRIGGER_CONDITIONS` 中 `LIVESTREAM` 类型定义了 `1_hour_before` 触发条件，但 `_check_days_offset_condition()` 中的 `condition_map` 没有对应的映射。这导致直播事件的"提前1小时提醒"永远不会触发。

**修复**：在 `condition_map` 中添加 `"1_hour_before": (days_diff == 0)`，当天匹配由调度频率（10分钟）保障精度。

**文件**：`server/src/plugins/schedule/event_models.py`

---

#### 问题 4：`get_events_due_for_trigger` 返回类型声明错误（已修复）

**严重性**：低

**描述**：函数声明返回 `List[Dict[str, Any]]`，但实际返回 `List[Tuple[Dict[str, Any], str]]`（含 trigger_key）。虽然 Python 运行时不受影响，但类型注解误导了调用方和理解。

**修复**：将返回类型改为 `List[tuple]`，并在文档字符串中明确说明。

**文件**：`server/src/plugins/schedule/event_store.py`

---

#### 问题 5：`OfficialFeedFetcher` 账号列表类型不一致（已修复）

**严重性**：高（运行时崩溃）

**描述**：`DEFAULT_BILI_ACCOUNTS` 定义为 `List[Tuple[str, str]]`（包含 uid 和名称），但 `self.bili_accounts` 声明为 `List[str]`，初始化时的三元表达式 `[uid for uid, _ in DEFAULT_BILI_ACCOUNTS]` 正确，但配置覆盖路径 `[str(a) for a in bili_accounts]` 会将单个字符串拆成字符。更严重的是，在 `_parse_bili_item()` 中 `for u, name in self.bili_accounts` 试图对 `List[str]` 做元组解包——如果走配置路径（纯字符串列表），这会立即抛 `ValueError`。

**修复**：
1. 将 `DEFAULT_BILI_ACCOUNTS` 改为 `List[str]`
2. 将 `_parse_bili_item` 中的账号名称查找改为字典映射

**文件**：`server/src/plugins/schedule/official_feed_fetcher.py`

---

### 2.3 日程唤起机制总结

| 唤起方式 | 调用链 | 状态 |
|---------|--------|------|
| 用户登录时唤起 | `ActivityMaker.dispatch_action(REGULAR_LOGIN)` → 检查节日/citywalk/新歌/重要日期 | ✅ |
| 周期性检查提醒 | `ScheduleManager._async_main()` 每 10 分钟 → `ReminderDispatcher.dispatch_all_due()` | ✅ |
| 重要日程注入上下文 | `TopicReplier._reply_one_topic()` → `ScheduleManager.get_active_context()` → `ActivityContextProvider.get_context()` | ✅ |
| 演唱会静默 | `ActivityMaker.dispatch_action()` → `ScheduleManager.is_silence_period()` | ✅ |

---

## 三、安全与性能问题

### 3.1 数据库连接管理

**当前状态**：✅ 良好

每个 `EventStore` 方法都使用 `try/finally` 模式确保 `db.close()` 被调用。`_get_session()` 每次创建新 session，符合 SQLite 的线程安全模型。

**注意**：`date_processor.py` 中的 `_save_user_date_event` 和 `get_today_important_dates` 也直接创建并关闭 session，模式正确。

### 3.2 Topic 处理时的数据库开销

**当前状态**：✅ **已优化**

`get_all_events()` 和 `get_events_due_for_trigger()` 现在具有**日级缓存**机制：
- 查询结果在**同一自然日**内复用，次日 00:00 自动过期
- 所有写操作（`add_event`、`_update_event`、`remove_event`、`mark_notified`）会立即清空缓存
- 使用 `threading.Lock` 保证跨线程安全（ScheduleManager 运行在独立线程，TopicReplier 在主线程）

**缓存收益估算**：
- 之前：每个 Topic 回复触发 1 次 `get_all_events()`，每 10 分钟调度触发 1 次 `get_events_due_for_trigger()`
- 现在：同一天内仅第 1 次触发 DB 查询，后续全部命中缓存（直到有事件写入）
- `ActivityContextProvider.get_context()` 间接受益于 `get_all_events()` 缓存

### 3.3 静默判断缓存

**当前状态**：✅ 良好

`ScheduleManager` 已有静默事件缓存（`_silence_cache`，TTL 1 小时，每次检查时重判），避免每次 `is_silence_period()` 都查数据库。

### 3.4 EventParser 安全考虑

**当前状态**：✅ 良好

- VLM/LLM 调用有完整的异常处理
- JSON 解析有容错处理（`_extract_json_array`）
- 有规则降级路径（`_rule_based_parse`）
- 图片下载有超时（15秒）和错误处理

### 3.5 Cookie 管理安全

**当前状态**：✅ 良好

- Cookie 文件使用 `utf-8-sig` 编码读取，去除 BOM
- B站 cookie 有逐字段过期解析
- Playwright 无头浏览器使用独立 context，不共享 cookie
- 合并策略是覆盖关键字段，保留 buvid 等不变

---

## 四、语法检查

所有 schedule 模块文件通过了 Pylance 语法检查：

- ✅ `event_store.py`
- ✅ `event_models.py`
- ✅ `schedule_manager.py`
- ✅ `reminder_dispatcher.py`
- ✅ `activity_context_provider.py`
- ✅ `event_parser.py`
- ✅ `official_feed_fetcher.py`
- ✅ `cookie_manager.py`
- ✅ `date_processor.py`

---

## 五、修复总结

| # | 问题 | 文件 | 严重性 |
|---|------|------|--------|
| 1 | `_save_user_date_event` 绕过了 EventStore API | `date_processor.py` | 中 |
| 2 | `ensure_holidays` 农历去重使用错误日期格式 | `event_store.py` | 高 |
| 3 | `check_trigger_condition` 缺失 `1_hour_before` | `event_models.py` | 高 |
| 4 | `get_events_due_for_trigger` 返回类型声明错误 | `event_store.py` | 低 |
| 5 | `OfficialFeedFetcher` 账号列表类型不一致 | `official_feed_fetcher.py` | 高 |

**总计修复**：5 个问题，涉及 4 个文件。

## 六、缓存优化（2026-05-25 追加）

为 `EventStore` 的 `get_all_events()` 和 `get_events_due_for_trigger()` 新增**日级内存缓存**：

**设计原则：**
- 绝大多数 Event 在同一天内不会变化，缓存到次日 00:00 自动失效
- 任何写操作（add/update/remove/mark_notified）立即清空缓存
- 使用 `threading.Lock` 保证 ScheduleManager（独立线程）和 TopicReplier（主线程）的并发安全

**实现细节：**
- 新增 `_all_events_cache`、`_due_events_cache`、`_cache_date` 三个缓存字段
- 新增 `_cache_valid()` 方法判断缓存是否在今日有效
- 新增 `_invalidate_cache()` 方法清空所有缓存（线程安全）
- `add_event`、`_update_event`、`remove_event`、`mark_notified` 写入后调用 `_invalidate_cache()`

**影响范围：**
- `ReminderDispatcher.dispatch_all_due()` → 受益于 `get_events_due_for_trigger` 缓存
- `ActivityContextProvider.get_context()` → 受益于 `get_all_events` 缓存
- `ScheduleManager.get_silence_event()` → 不受影响（使用独立缓存 `_silence_cache`)

---

## 七、过期事件清理（2026-05-25 追加）

### 7.1 EventStore.purge_expired_events()

新增 `purge_expired_events(today)` 方法，在凌晨调度中每日执行一次：

**清理规则：**
- **周期性事件**（`is_recurring=True`）：永不过期，不清除
- **用户个人事件**（`source="user"`）：保留（生日/纪念日常年有效）
- **有 `end_datetime`**：`end_datetime` < 今天 → 标记 `is_active=False`
- **只有 `start_datetime`**：`start_datetime + 1天` < 今天 → 标记不活跃（给 1 天缓冲）
- **只有 `date_mmdd` 无具体 datetime**：跳过（无法判定年份）

### 7.2 DailyScheduler 集成

`_run_once_for_day()` 在凌晨 4 点执行时，**先清理过期事件，再写入新事件**，确保：
1. 旧演唱会/直播事件不会无限积累
2. 周期性节假日和用户生日不受影响
3. 缓存随清理自动失效

---

## 八、ActivityContextProvider 优化（2026-05-25 追加）

### 8.1 限制 7 天内活动

`get_context()` 现在过滤 `start_datetime`：
- 只返回 `now <= start_datetime <= now + lookahead_days(7)` 的活动
- 已过去的演唱会不会再出现在上下文注入中
- 没有 `start_datetime` 的事件直接跳过

### 8.2 日级缓存

与 `EventStore` 类似的缓存策略：
- `_context_cache: Dict[str, str]` — per-user 上下文字符串缓存
- `_cache_date` — 缓存日期，次日 00:00 自动失效
- `threading.Lock` 保证线程安全
- `clear_mention_log()` 也会清空缓存

**缓存收益**：同一天同一用户多次 topic 回复，`get_context()` 只执行一次完整逻辑（过滤 + 排序 + 频率控制），后续直接返回缓存字符串。

---

## 九、ActivityMaker 登录事件统一检索（2026-05-25 追加）

### 9.1 问题

`REGULAR_LOGIN` 中 2/3/4 类事件（citywalk、学新歌、重要日期）各自独立检索：
- citywalk 直接读 citywalk_reports 目录
- 学新歌读 `newly_learned_songs.json` 文件
- 重要日期直接查 Event 表

这导致：即使 `ReminderDispatcher` 已经向用户推送过这些事件，登录时仍会重复提示。

### 9.2 修复

统一使用 `EventStore.get_events_due_for_trigger()` 检索 `travel`/`new_song`/`birthday`/`anniversary` 类型事件，并在提示后立即调用 `mark_notified()`，确保：
- 登录提示和周期性提醒不会重复
- 同一事件不会向同一用户提示两次
- 所有事件检索走同一入口，逻辑统一
