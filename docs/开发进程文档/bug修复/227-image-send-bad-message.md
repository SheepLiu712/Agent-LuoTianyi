# #227 · 0.3.2 版本：PC 端无法发送图片（服务器返回 [BAD_MESSAGE]，报错需细化）

| 项 | 值 |
| --- | --- |
| 分支 | `fix/image-send-bad-message` |
| Issue | [#227](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/227) |
| 来源 | 《AgentLuo bug收集》（腾讯文档） |
| 流程 | 普通修复：dev → fix/ → PR → dev |
| 状态 | 实现完成，待验证 |

## 触发条件
PC 端发送的图片在服务端校验失败（格式 / 大小 / 配置缺失）时，仅得到笼统 `[BAD_MESSAGE] chat event payload is invalid`，无法定位原因。

## 被违反的不变量
- 图片发送要么成功，要么得到可解释的失败原因；
- 客户端声明的图片属性（MIME / 大小）与服务端校验语义一致。

## 根因（详见 #227 调查记录）
- 错误收敛：`adapter.py:81` 吞异常 → `endpoint.py:139` 固定文案，原文丢失；
- 声明/校验不一致：客户端按扩展名推断 MIME（未知兜底 `image/png`）、自身白名单未使用；服务端 PIL 实解严格比对；对话框放行 `.svg/.xpm`；
- `media_store` 缺失（旧 config）时全拒且无告警。

## 修复点
1. 结构化错误透传：沿用 ack 的 `code` / `message` / `retryable` 字段返回媒体错误码，保持旧客户端兼容；
2. 客户端发送前启用 `image_rules` 预检；对话框过滤器与服务端白名单对齐；
3. `media_store` 缺省时启动告警，杜绝「静默全拒」。

## 改动范围
server：`adapter.py` / `_input.py` / `endpoint.py`（+ ack 结构、评估《统一事件协议》同步）；
client：`image_encoding.py` / `image_rules.py` / `gui/main_ui.py`；补端到端契约测试。

## 验收标准（拟 · 待人审）
- 异常图片收到具体原因（格式不支持 / 图片过大 / 配置缺失）；
- 合法 PNG/JPG 正常发送；两类场景均有测试证据。

## 验证计划
- server 单测 + 契约测试（真实客户端 payload 产物 → adapter）；
- PC 手工回归（正常 / 异常格式 / 超限）。

## 待定与前置
- ack detail 扩展与《统一事件协议》的同步确认；
- 真实失败样本（用于验证）。
