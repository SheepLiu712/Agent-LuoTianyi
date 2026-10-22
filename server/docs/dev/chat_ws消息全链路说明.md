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

共享技能仍由 `Skills` 持有，例如输入预处理、对话压缩、说话与演唱。handler 只依赖所需技能的窄接口，不读取角色聚合对象。

## 出站链路

1. `ChatReplyHandler` 生成 `ReplyDraft`，持久化正式对话记录，并提交 `ActionPlan`。
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
