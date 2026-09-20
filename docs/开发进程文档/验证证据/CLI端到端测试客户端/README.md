# CLI 端到端测试客户端 · 真实链路验证证据（脱敏）

- 验证对象：分支 `feat/cli-e2e-s3b-next-reply`（PR #185；含 S3b 等待下一条回复、UTF-8 修复、S8b 偏好响应归一化）
- 验证时间：2026-09-20
- 目标部署：`https://www-api.u3493359.nyat.app:11664`（release）
- 测试账号：临时注册（邀请码注册）；本证据已脱敏（见文末）
- 运行方式：`cd client && python cli.py --scenario <请求文件>`；stdout 为 UTF-8 JSONL 动作记录（`action_result` / `scenario_result`），诊断日志全部在 stderr

## 目录

- `requests/`：请求体（场景文件）。为可读性做了 JSON 格式化，仍可直接作为 `--scenario` 输入（替换占位符后）
- `responses/`：对应运行的真实 stdout JSONL（原始记录，逐行 JSON）
- `findings/`：首测发现的缺陷与行为记录（复现证据）

## 复现步骤

1. 注册账号（客户端调用）：
   - `NetworkClient.register(username, password, invite_code)` → `POST /auth/register`
   - 请求体形状：`{"username": "<your-user>", "password": "<客户端公钥加密后的密码>", "invite_code": "<invite-code>"}`
   - 成功返回：`{"message": "注册成功", "user_id": "<your-user>"}`
2. 替换 `requests/*.json` 中的占位符：`cli_e2e_user` → 你的用户名；`<redacted-password>` → 你的密码；`<TEMP>/cli_e2e_image.png` → 本机图片路径（可用 `requests/07-image-generate.py` 生成同款 512×512 测试图：红圆 + 蓝方块 + 文字）。
3. 逐条运行：`python cli.py --scenario requests/0X-*.json > out.jsonl`，对照 `responses/0X-*.jsonl`。

## 结果摘要

| # | 链路 | 动作 | 结果 |
| --- | --- | --- | --- |
| 01 | 文本 | connect / send_text / reply.wait | ✅ 完整回复（文本 + 表情 ×4"卖萌" + TTS 296,012B WAV 落盘） |
| 02 | 动态 + 偏好读取 | preferences.open / dynamics.open | ✅ 10 条真实动态、`marked_read=true`、偏好快照 `{}` |
| 03 | 动态发布 | dynamics.post | ✅ `visible=true`（账号私有可见） |
| 04 | 动态读取 + 翻页 | open / read / load | ✅ 帖子 + 评论、游标翻页 + 稳定去重（count 10、`has_more=true`） |
| 05 | 偏好写入 + 清理 | update / replace 清理 / open 复核 | ✅ `confirmed=true`、清理后 `{}` |
| 06 | 触摸 | touch.send / reply.wait | ✅ 服务端触摸反射（`touch-` UUID、空文本、`moemoe` 表情、`is_ephemeral=true`、`display_in_chat=false`） |
| 07 | 图片 | select / send / reply.wait | ✅ 视觉回复"哇，这个红蓝配色的图看起来好醒目呀！"（8.8s、TTS 274,500B WAV 落盘） |

## findings（首测发现）

1. `01-stdout-encoding-mojibake.jsonl`：**产品缺陷（已修复 `f31d5df`）**——Windows 下重定向 stdout 使用本地编码（GBK），JSONL 中文损坏；`responses/01` 为修复后干净输出。
2. `02-preferences-ack-false-negative.jsonl`：**产品缺陷（已修复 `c573ad1`，S8b）**——`preferences.update` 把服务端成功响应 `{"status":"success"}`（无 `ok` 字段）误判为 `ACK_REJECTED`，实际写入已生效；`responses/05` 为修复后。
3. `03-touch-ephemeral-empty-text.jsonl`：**行为发现（测试假设修正，非产品缺陷）**——触摸回复为服务端设计内"临时音频反射"（空文本、不显示在聊天、不落盘），`reply.wait` 的 `non_empty` 断言不适用于该路径；`responses/06` 为按设计修正后的通过记录。

## 脱敏说明

- 已替换：用户名 → `cli_e2e_user`；密码 → `<redacted-password>`；邀请码 → `<redacted-invite-code>`；账号 UUID → `<user-uuid>`；本机临时目录绝对路径 → `<TEMP>`
- 保留：目标部署地址、会话 / 动作 / 回复 UUID、时间戳（保证证据可追溯）
- 客户端 JSONL 契约本身不输出凭据（SPEC §1.5）；证据文件中不含任何令牌
- 自动泄露自检：对全部证据文件扫描上述敏感串，结果为 CLEAN
