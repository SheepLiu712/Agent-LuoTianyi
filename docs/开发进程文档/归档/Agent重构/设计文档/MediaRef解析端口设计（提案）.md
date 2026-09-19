# MediaRef 解析端口设计（提案，未实现）

- 状态：**设计提案**。端口归属与 `media_ref` 永久性已由 owner 确认（见 §3.5）；本文仍只记录方案与影响，**不实现、不修改 interface 文档的当前事实、不接入生产**。
- 关联工单：Issue [#68](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/68)（09 图片预处理落库）的前置设计
- 相关规范：总 SPEC 第 4.2 节「受控领域引用」；[领域词汇](../../../../../CONTEXT.md) 的 Controlled Domain Reference；[接口文档阅读约定](../../../../项目说明/项目架构与接口（spec）/接口文档/README.md)

## 1. 要解决的问题

新 Agent 的 `ImageMessage` / `VoiceMessage` 只携带受控引用 `MediaRef(media_id: str)`，不携带 base64、路径或供应商对象（见 `server/src/domain/agent/stimulus.py`、`stimulus_values.py`）。当前 `server/src` 内**没有任何把 `MediaRef` 解析成媒体内容的端口或存储**，因此 09「图片预处理落库」无法取得图片内容去调用图片理解。

本次明确不做：不实现 09、不新增代码、不改动 WebSocket 协议、不改变 `MediaRef` 的公开字段。

## 2. 代码放在哪里、为什么

- 解析实现属于**基础设施**：媒体可能是客户端上传文件、对象存储或外部 URL，属于 `system` / `capabilities` 一侧，不是 Agent 内部认知。
- Agent 侧只应接受**受控引用**并按需经注入的端口读取；不得把本地路径、凭据或供应商对象带进 Agent（总 SPEC 4.2、A7）。
- 因此建议新增一个**窄端口（seam）**，由 `SystemRuntime` 显式装配，Agent 的图片/语音理解技能注入。

## 3. 建议 interface（目标，未实现）

```python
@dataclass(frozen=True)
class ResolvedMedia:
    data: bytes
    mime_type: str

class MediaResolver(Protocol):
    def resolve(self, media_ref: MediaRef) -> ResolvedMedia: ...
```

- **调用者**：Agent 的图片/语音理解技能（经构造注入）；Adapter 仍只负责把外部消息转成携带 `MediaRef` 的 Stimulus。
- **输入/输出**：输入名义 `media_id`，输出编码字节与 MIME；不返回本地路径、URL 凭据或供应商对象。
- **副作用**：只读，无持久化、无网络写。
- **正常行为**：按 `media_id` 返回内容与 MIME。
- **异常行为**：未知 / 过期 / 未授权 → 稳定、可分类的错误；内容为空 → 明确失败，不静默返回空。
- **并发/失败**：同一引用可重复解析（幂等读）；超时或依赖不可用由调用方按稳定错误码处理。

## 3.5 媒体来源与 `media_ref` 的产生（owner 裁决，已确认）

解析放在 Agent 侧没有问题（§3）。本节补齐原提案缺失的另一半：**媒体源如何产生 `media_ref`**。

- **Adapter 直接落库数据并产生 `media_ref`**：外部媒体到达时，由 Adapter（system 侧）完成校验与原始数据持久化，并生成 `MediaRef(media_id)`；**Agent 不负责落库**。
- **`media_ref` 必须永久**：Agent 可能不会及时回复（批次等待、被新内容取消、晚返回丢弃），引用不得因 TTL 或清理而失效。
- **Agent 只解析、可更新词条**：Agent 经注入的 `MediaResolver` 读取内容用于理解；理解结果（词条）可以在预处理后更新，`context` 随时更新。
- **归属结论**：存储与引用产生 = Adapter / system；解析端口 = Agent 经构造注入（实现可由 `system` / `capabilities` 装配）。因此本提案的「未决」中**不再包含 TTL/清理语义**。

## 4. 备选方案

| 方案 | 归属 | 优点 | 代价 |
| --- | --- | --- | --- |
| A. `capabilities` 提供 `MediaResolver`，Agent 技能注入 | capabilities + agent 技能 | 与图片理解能力同域，Agent 边界不变 | 需新增能力与装配；授权主体需明确 |
| B. Adapter 解析后写入受控缓存，Agent 只读引用 | system/adapter | Agent 不接触存储 | 需引入缓存生命周期与 TTL；stage 需管理引用 |
| C. 预处理阶段（stage/外部）先解析落库，Agent 只读落库结果 | stage/system | Agent 完全不解析媒体 | 把「理解」职责移出 Agent，与总 SPEC 4.2 的认知归属冲突 |

倾向 **A**：解析是「怎么取到内容」的技术能力，理解与持久化判断仍留在 Agent 技能内。

## 5. 影响面

- **Adapter / system**：新增端口实现与 `SystemRuntime` 装配。
- **Agent**：新增图片/语音理解技能持有的端口依赖；handler 经技能访问，不直连存储。
- **interface 文档**：确认后需在 `接口文档/capabilities/` 与 `接口文档/system/` 增加端口条目（当前未改）。
- **测试**：Fake Resolver 需遵守与生产实现相同的调用约定（未知/空/失败）。
- **兼容性**：`MediaRef` 已是公开领域类型，端口是**新增 seam**，不改变既有 Stimulus 字段与 WebSocket 协议；不存在旧调用方需要迁移。
- **安全**：授权主体（用户/角色）与大文件/超时策略尚未确定，必须在实现前写入 spec；`media_ref` 的**永久性**已裁决（§3.5），解析端只读且不引入 TTL。

## 6. 未决问题（评审需回答）

1. **授权主体**：Adapter 落库并产生引用时按 `(user_id, character_id)` 归属校验，还是全局？（解析端只读）
2. ~~媒体 TTL、清理与失效语义？~~ → **已裁决（§3.5）：`media_ref` 永久有效，不设 TTL/清理**，因为 Agent 可能不及时回复。
3. 大文件分块/超时上限？
4. 图片与语音是否复用同一端口，还是各自端口？
5. 解析失败时 09 的行为：`FAILED / INTERNAL_ERROR` 并丢弃该输入，还是保留等待重试（按现行「不自动重试」原则应前者）？

## 7. 明确不包含

- 本次只写设计提案；不新增产品代码、测试、公开 interface 或配置。
- 不实现 09，不修改现有 `interface 文档` 的当前事实描述。
- 不改变 `MediaRef`、`ImageMessage`、`VoiceMessage` 的字段与校验。
