# Chat WebSocket 消息全链路

本文记录 Agent contract 收口后的唯一生产链路。旧 `chat_session`、`subconscious`、`legacy` 包已删除，不再作为兼容入口或运行时对象图存在。

## 实现位置

聊天门面为 `src.adapter.websocket.chat.WebSocketAdapter`。`chat/` 内部持有输入转换、语音上传、输出投递、连接状态和客户端模型委托；`websocket/connection.py` 是聊天与通话共用的网络契约，根包不再导出聊天实现。

聊天切换通话通过公开的 `call_v1.chat_switch` 解析原始 `call.switch_prepare`，将角色 ID 与请求 ID 交给 StageManager；接受准备后由同一协议入口构造 `call.switch_ready`。聊天不引用通话私有解析器，协议入口也不管理 Stage 或切换状态。

## 入站链路

1. `web.websocket.endpoint` 完成物理连接与认证，调用 Adapter.open 获取不透明连接句柄；chat.ready 由 Adapter 在成功绑定后排队。
2. Web 只检查 ASGI 消息形状及通用大小限制，将原始 str/bytes 交给 `WebSocketAdapter.receive`。
3. Adapter 统一解析 JSON、消息 ID、去重、心跳、模型响应及语音上传，生成 ACK/NACK；刺激交给 Stage，切换等生命周期请求交给 StageManager。输入准入由 Stage 判断。
4. `ChatStage` 持有 pending、调度、取消和交互修订；到期时只调用 `Agent.handle_stimulus`。
5. `StimulusRouter` 把强类型刺激路由到对应 handler。文本/图片等输入先预处理；回复到期由 `ChatReplyHandler` 处理。

## Agent 内部

`AgentRuntime` 是组装根，但不再构造 `CharacterRuntime` 或意识/潜意识聚合对象。每个启用角色直接拥有四类私有技能：

- `AgentMemory`：长期记忆召回、写入和用户画像适配；
- `CharacterReplyGenerator`：角色提示组装、模型调用与结构化回复解析；
- `ResponseCompositionSkill`：组合记忆召回、演唱计划、回复生成和歌词补全；
- `ReflectionSkill`：结算后的记忆沉淀与画像更新。

共享技能由技能门面持有，例如输入预处理、对话压缩、说话与演唱。[ReplySkill](../../src/agent/skills/cognitive/reply.py) 是聊天与通话共用的回复技能，负责流式回复解析及行动计划交付；角色私有技能继续负责提示、记忆与歌曲准备。handler 只依赖所需技能的窄接口，不读取角色聚合对象。

## 出站链路

1. `ChatReplyHandler` 通过共享回复技能生成 `ReplyDraft`，持久化正式对话记录，并增量提交 `ActionPlan`。可朗读正文超过 7 字且遇到标点即可交付短句，不等待全文；情绪切换和正常结束时交付尾段。已选演唱计划仍等待全文并沿用原有解析。
2. `ChatStage` 接受计划并调用 `Agent.realize_action_plan`。
3. `ActionRouter` 将 `Say`、`Sing` 等行动交给对应 handler。
4. handler 经 Stage 的类型化输出 sink 交付 `StageOutput`，Adapter 负责协议编码、顺序排队、取消和背压。
5. Web 的发送循环调用 `next_output`，按报文类型发送，再通过 `complete_output` 反馈成功、失败或取消。输出出队不等于网络发送完成，网络完成也不代表客户端确认或播放结束。

## 边界约束

- 外部认知调用只有 `handle_stimulus` 与 `realize_action_plan`，调用点只允许在 Stage。
- Web 层接收原始消息；Adapter 负责转换为强类型刺激。Stage 不接触 WSMessage、物理 socket 或 call.v1 协议状态。
- Agent 记忆实现位于 `src/agent/skills/adapters/memory`；歌曲知识数据库与实体链接位于 `src/infrastructure/song_knowledge`。
- 架构扫描禁止重新引入 `src.chat_session`、`src.subconscious`、`src.legacy`、旧领域刺激或旧角色对象图。
- wheel 打包测试同时验证新包存在、三个旧包不存在。

静态验收命令：

```powershell
python scripts/check_architecture_boundaries.py
```

## 客户端模型流式委托

[LLMModule](../../src/infrastructure/models/llm/module.py) 封装模型调用，创建时接受 `stream` 选项，默认关闭，模块配置 `llm.stream` 优先。角色装配为 `main_chat` 回复模块开启流式生成。其 `generate_response` 方法在生成过程中通过 `on_delta` 回调交付正文增量，结束后仍返回完整文本；未提供回调时聚合全文，供演唱等原有完整解析流程使用。

[ClientLLMExecutor](../../src/adapter/websocket/chat/client_model_executor.py) 负责 WebSocket 委托请求、连接归属和增量校验。客户端只调用供应商模型并返回正文；分句、情绪与表情映射、记忆和行动计划仍由服务端处理。这里的模型流序号与 `call.v1` 音频协议序号无关。

### 能力协商与消息

客户端在 `llm_mode` 中声明启用的模型类型与流式能力，例如 `{"types":["main_chat"],"stream":true}`。未启用对应类型或没有可用连接时，模型调用使用服务端接口；已启用类型但未声明流式能力的旧客户端不能承接流式请求，服务端明确报错要求升级。非流式请求仍兼容原有完整结果协议。

以下示例均为消息的 `payload`，外层仍使用既有事件信封：

| 事件类型 | 方向 | 负载约定 |
| --- | --- | --- |
| `llm_request` | 服务端 → 客户端 | 保留 `request_id`、模型类型、提示和参数等既有字段，流式请求增加 `stream: true` |
| `llm_response` | 客户端 → 服务端 | 正文增量：`{"request_id":"r1","sequence":0,"delta":"[中性]今天我们一起去公园吧。"}` |
| `llm_response` | 客户端 → 服务端 | 正常结束：`{"request_id":"r1","sequence":1,"done":true,"content":"[中性]今天我们一起去公园吧。","usage":null}` |
| `llm_response` | 客户端 → 服务端 | 失败：`{"request_id":"r1","error":"错误说明"}`，终止当前请求 |
| `llm_cancel` | 服务端 → 客户端 | 取消：`{"request_id":"r1"}`，停止对应模型请求 |

每个请求的 `sequence` 从 0 开始连续递增，结束包使用下一个序号。序号必须为整数，正文增量必须为非空字符串；结束包的 `content` 必须严格等于此前增量拼接的结果。重复、跳号或全文不一致直接失败，结束包不会再次触发 TTS。错误包不要求序号。

### 取消、连接归属与失败

请求绑定发起时的连接。服务端忽略其他连接的回包及请求清理后的迟到回包，使用有界队列接纳增量，队列溢出直接失败。等待超时、消费者取消或增量校验失败时清理请求，并对仍在途的请求发送 `llm_cancel`；客户端收到取消或断线后关闭上游模型流，旧请求不得向重连后的新连接回传结果。

委托开始后发生失败直接向调用方报告，不切换服务端重新生成已经输出的前缀。服务端直接调用供应商时同样逐次消费服务器发送事件（SSE），取消时关闭 HTTP 流，异常结束不作为完整回复成功返回。

### 客户端实现与验证入口

- 桌面端：[llm_client.py](../../../client/src/utils/llm_client.py) 使用 HTTPX 异步读取供应商流；[ws_transport.py](../../../client/src/network/ws_transport.py) 逐增量发送序号并处理取消。模型密钥保留在客户端配置中，不回传服务端。
- 移动端：[llm_client.ts](../../../app/utils/llm_client.ts) 使用 `expo/fetch` 读取响应流并处理跨分片字符；[ws_transport.ts](../../../app/utils/ws_transport.ts) 管理序号、原连接归属和请求中止。
- 命令行端：[ws_transport.py](../../../cli-client/cli_client/network/ws_transport.py) 同步支持增量回调与取消协议；此改动不增加命令行模型配置或模型执行器。
- 服务端协议验证：[test_client_llm_stream.py](../../tests/integration/websocket/test_client_llm_stream.py)。桌面与移动端验证分别见 [test_llm_stream.py](../../../client/tests/test_llm_stream.py) 和 [llm_stream.test.ts](../../../app/__tests__/llm_stream.test.ts)。

共享回复的分句、情绪映射和播放结算规则见[通话规范 AC-07](../../../docs/开发进程文档/用户实时语音通话-spec.md#ac-07-agent-回复与双通道路由)。协议支持增量返回不等于真实通话首音频包延迟已达标。


## 统一业务输入处理

`_input.process_input` 返回 `(stimulus_or_none, status)`，status 为普通字典：`complete` 要求投递完整刺激，`partial` 只确认上传步骤，`duplicate` 重放幂等应答，`error` 携带处理错误。文字、图片、录音协调和语音上传从同一入口进入。图片仍在初步准入后物化，并在异步物化后复查绑定。

`_voice_upload_helper.py` 不持有可调用的输入 sink，不做准入和投递。begin/finalize/有效 abort 返回的刺激由 Adapter 提交；只有 submit 成功才提交 helper 的候选状态并发送成功 ACK。分块 ACK 不代表完整语音进入 Stage。校验失败和过期通知暂存在 helper，由 Adapter 取出并向有效的原绑定投递。


### 聊天下行协议编码与连接状态


聊天下行的事件信封（`type / ts / payload / reply_to`）构造与 wire JSON 序列化统一由 `chat/_protocol_translate.py` 完成。`encode_event` 构造并编码聊天事件，`encode_message` 编码已经成形的协议消息（例如切换就绪响应），避免重复套信封。`_binding.py` 的 `Binding` 统一持有连接身份、协商状态、就绪门控、唯一 Stage 及绑定有效状态、控制任务及发送队列；协议编码仍调用 `_protocol_translate.py`。

业务输出与客户端模型请求先编码，再调用 `binding.send(str | bytes)`；该方法等待业务就绪并等待 Outbox 的网络完成结果。`chat.ready`、ACK/NACK 和心跳等即时协议消息由 `_protocol_translate` 编码后调用 `Binding.enqueue` 入队，不等待业务就绪门控。保持 `chat.ready` 先入队再释放业务门控的顺序，避免循环等待。入队、出队、网络发送完成、客户端确认及播放完成仍是不同事实；等待者取消不撤回已入队的报文。

`_delivery.py` 继续管理业务消息分组、顺序、取消与终包；`_binding.py` 内部的私有 Outbox 管理已编码报文的容量、在途状态和发送完成反馈，外部不直接操作队列。投递器由 Binding 持有，Adapter 不再另行管理其生命周期。业务身份生成与持久化中的 JSON 使用不属于 wire 序列化，不受此次归属调整影响。

### 聊天连接 Binding 的归属

Adapter 维护连接句柄到 Binding 的集合，以及用于 Stage 输出路由的交互索引。创建、撤销 Stage 绑定和网络收发反馈均通过 Binding 操作，不再维护独立的 Peer、Outbox 或连接投递器集合。`_BoundInputSink` 已删除，Binding 自行检查权限并提交刺激。

一条连接只绑定一个 Stage，Binding 直接持有该 Stage、输入权限及输出收尾状态，不再设置 Stage 集合或额外绑定记录。解绑永久撤销业务投递权限，取消业务输出并等待控制任务；WebSocket 仍可发送协议控制响应，真正断线才关闭发送队列。重连接入创建新的 Binding，异步媒体转换及语音上传持有的旧 Binding 始终失效。
