# Live2D 触摸交互功能实现说明

## 概述

本实现为 Agent-LuoTianyi 项目增加了用户与 Live2D 模型的直接触摸交互能力，涵盖 PC 客户端（PySide6）和安卓客户端（React Native），以及服务端处理逻辑。

## 修改的文件清单

### 模型配置
| 文件 | 修改 |
|---|---|
| `client/res/live2d/models/luo/model.model3.json` | 新增 5 个 HitArea（身体/裙子/右腿/左手/右手） |
| `app/public/live2d/models/luo/model.model3.json` | 同上 |

### PC 客户端
| 文件 | 修改 |
|---|---|
| `client/src/gui/main_ui.py` | 目光跟随插值、全区域触摸检测、蓝色圆环反馈、新 payload 格式 |
| `client/src/gui/binder.py` | `on_send_touch()` 支持 `touch_meta` 参数 |
| `client/src/network/ws_transport.py` | `submit_user_touch()` 支持 `touch_meta` 和数组格式 |
| `client/src/network/network_client.py` | `send_touch()` 透传新参数 |
| `client/src/message_process/message_processor.py` | `send_touch()` 透传新参数，dispatch 解析新格式 |

### 安卓客户端
| 文件 | 修改 |
|---|---|
| `app/public/live2d/live2d.html` | 目光插值圆环反馈、触摸事件固定、频率控制 |
| `app/utils/binder.ts` | `sendTouch()` 新增 `touchMeta` 参数 |
| `app/hooks/useChatLogic.ts` | `handleWebViewMessage` 解析新格式 |
| `app/utils/message_processor.ts` | `sendTouch()` 透传新参数 |
| `app/utils/network_client.ts` | `sendTouch()` 透传新参数 |
| `app/utils/ws_transport.ts` | `submitUserTouch()` 支持新格式 |

### 服务端
| 文件 | 修改 |
|---|---|
| `server/src/interface/websocket_service.py` | `convert_to_chat_input_event` 兼容新旧 payload |
| `server/src/pipeline/topic_planner.py` | `_handle_touch_event()` 绕过缓冲直接生成 Topic |
| `server/src/pipeline/topic_replier.py` | 触摸指针机制 + `asyncio.Lock` |

---

## 详细实现

### 1. 目光跟随完善

#### PC 客户端 (`main_ui.py:Live2DWidget`)

**原行为**: `mouseMoveEvent` 直接将鼠标坐标传给 `model.Drag()`，鼠标离开后无变化。

**新行为**:
- `_gaze_target_x/y`：目标坐标（由 `mouseMoveEvent` 和 `leaveEvent` 设置）
- `_gaze_current_x/y`：当前插值坐标
- `timerEvent`（~60fps）：每帧以 0.15 系数向目标插值，平滑收敛
- `mouseMoveEvent`：鼠标在控件内时跟随；在外时目标设为控件中心
- `leaveEvent` / `enterEvent`：管理 `_mouse_inside` 标记

拖拽到控件外时，鼠标位置超出边界被 `mouseMoveEvent` 检测到，目标自动设为控件中心，插值动画平滑回到默认位置。

#### 安卓客户端 (`live2d.html`)

**原行为**: `pointermove`/`touchmove` 直接调用 `model.focus(clientX, clientY)`。

**新行为**:
- `gazeTargetX/Y` / `gazeCurrentX/Y` 分离跟踪目标和插值
- `gazeAnimationLoop()`：独立 requestAnimationFrame 循环，0.12 系数插值
- `canvas.addEventListener('pointerleave', resetGaze)`：指针离开画布时回到屏幕中心

### 2. 触摸事件感知与客户端处理

#### HitArea 配置

模型 `model.model3.json` 的 `HitAreas` 数组新增：
- `"身体"` → `ArtMesh88`
- `"裙子"` → `ArtMesh91`
- `"右腿"` → `ArtMesh98`
- `"左手"` → `ArtMesh116`
- `"右手"` → `ArtMesh127`

触摸区域分组映射（`_area_to_group`）：
- `head`: 头, 辫子, 耳机
- `body`: 身体, 裙子, 袖, 8
- `legs`: 左腿, 右腿
- `hands`: 左手, 右手

#### 触摸动作定义

- **PC**: 鼠标左键点击（`mousePressEvent`）
- **安卓**: 屏幕轻触（`pixi-live2d-display` 的 `model.on('hit')` 事件，由 Cubism 判断）

#### 视觉反馈

- **PC** (`main_ui.py`): 在 `paintGL()` 中用 `QPainter` 绘制浅蓝色圆环（`#ADD8E6`），60ms 间隔扩大，0.5 秒淡出
- **安卓** (`live2d.html`): 在 `PIXI.Graphics` 上绘制圆环，PIXI ticker 驱动动画

#### WebSocket 通讯（新 payload 格式）

```json
{
  "type": "user_touch",
  "payload": {
    "touchArea": ["head", "body"],
    "timeSinceLastSentTouch": 0.5,
    "touchCount": 3
  }
}
```

向下兼容旧格式：
```json
{
  "type": "user_touch",
  "payload": {
    "touch_area": "头",
    "click_frequency": {"count_10s": 2, "count_30s": 5}
  }
}
```

#### 频率控制

客户端限制：最大每秒发送一次触摸事件。代码中将 `_touch_send_interval` 设为 1.0 秒。在间隔内发生的触摸只累计计数和区域，不发送新包，到间隔期满后合并发送。

### 3. 服务端处理

#### 事件转换 (`websocket_service.py:convert_to_chat_input_event`)

- 兼容 `touchArea`（数组）和 `touch_area`（字符串）两种格式
- 将区域名映射为中文描述短语，多个区域用分号连接
- 附加 `timeSinceLastSentTouch` 和 `touchCount` 信息

#### 直接生成 Topic (`topic_planner.py:feed_unread_message`)

当事件类型为 `USER_TOUCH` 时：
1. 调用 `_handle_touch_event()`
2. 直接构建 `ExtractedTopic`（无需经过 unread_store 缓冲）
3. 调用 `_consume_topics([touch_topic])` 送入 `topic_replier.add_topic()`

#### 指针机制 (`topic_replier.py`)

在 `TopicReplier` 中维护三个状态：

| 状态 | 条件 | 行为 |
|---|---|---|
| IDLE | `_touch_pending is None` | 新 Topic 入队，设置指针 |
| QUEUED | `_touch_pending is not None` and not `_touch_processing` | 更新已有 Topic 内容，不入新队列 |
| PROCESSING | `_touch_processing is True` | 忽略新触摸事件 |

- `_touch_lock`（`asyncio.Lock`）：保证指针操作的并发安全
- `topic_processor` 在处理开始/结束时加解锁
- `add_topic` 在入队和更新时加锁

### 4. 修复的 Bug

**安卓客户端修复**: `live2d.html` 原来发送 `type: 'hit'`，但 `useChatLogic.ts` 检查 `data.type === 'touch'`，导致触摸事件从未到达服务端。已将 HTML 发送类型改为 `'touch'`，与服务端处理逻辑对齐。

---

## 与现有模块的集成

### 事件流

```
客户端点击/触摸
  → Live2D 区域检测（HitTest / model.on('hit')）
  → 视觉反馈（蓝色圆环）
  → WebSocket (user_touch) → 服务端
    → websocket_service.convert_to_chat_input_event()
      → ChatStream.feed_event()
        → ingress_worker_loop()
          → _process_ingress_event()
            → activity_maker.on_user_message()
            → ingress_message()（提取歌曲/日期，无害）
            → agent.add_conversation()（落库）
            → topic_planner.feed_unread_message()
              → _handle_touch_event()（绕过缓冲）
                → topic_replier.add_topic()（指针检查）
                  → topic_processor()
                    → _reply_one_topic()（正常回复流程）
                      → speaking worker → TTS → WebSocket 返回
```

### 兼容性

- 旧格式客户端（发送 `touch_area: "头"`）与服务端旧格式完全兼容
- 新格式客户端发送的数据可被旧服务端部分解析（`touch_area` 字段缺失时降级）
- 服务端 `_is_touch_topic()` 通过内容前缀 `[` + 触摸关键词启发式判断

### 安全与性能

- 客户端限流 1次/秒，防止服务端过载
- 服务端 `asyncio.Lock` 保证并发安全
- 触摸事件不经 unread_store 缓冲，减少延迟
