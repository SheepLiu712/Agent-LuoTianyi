# feat/voice 集成审查（head `d4b0ac6`）修复记录

| 项 | 值 |
| --- | --- |
| 分支 | `bugfix/voice-review-fixes`（基于 `feat/voice` @ `d4b0ac6`） |
| 来源 | 集成前深度审查：7 项阻断 N1–N4、N6–N8（N5 复核后降级为 P2） |
| 流程 | 普通 Bug 修复：`bugfix/*` → PR → `feat/voice`（缺陷只存在于特性分支） |
| 状态 | 修复完成，离线门禁全绿；真实服务端 AC-27 未执行（当前无运行本分支的服务端） |

## 触发条件与受影响范围

- **图片发送回归（N1）**：真机/桌面端发送真实照片 → 服务端 `BAD_MESSAGE: message exceeds the inbound frame limit`，气泡停留等待/失败。
- **语音核心旅程断裂（N2/N3/N7）**：发完一条语音后无法再次录音、无法切回文字模式；失败气泡的失败图标接的是播放而不是重传；`upload_id` 不是 UUID，真实服务端一律拒绝。
- **门禁与容量边界（N4/N8）**：未配置 `QWEN_API_KEY` 的部署核心校验直接失败（`test_admin_runtime` 3 例红）；`_completed` 幂等缓存保存原始分片字节且无条数上限。
- **跨端契约断裂（N6）**：AC-27 驱动等待服务端从不发射的 `listening`，且协议文档错列了 `agent_state` 取值。
- 受影响范围：`server/`（web 传输、adapter 语音上传、infrastructure 校验/向量、agent 音频理解）、`app/`（录音状态机与上传）、`cli-client/`（历史兼容与 AC-27 驱动）、协议与进程文档。

## 被违反的不变量

1. 入站帧上限必须 ≥ 媒体库允许的最大 base64 图片长度（既有图片能力不得因新增帧检查而回归）。
2. 语音提交后状态机必须回到可再次录音的稳定状态；`Uploading` 不得锁死模式切换与后续录音。
3. 服务端 `user_voice` 协议要求 `upload_id` 为 UUID，客户端必须生成规范 UUID。
4. 核心配置校验不得因可选能力（音频理解）缺配置而阻断业务运行时启动。
5. finalize 幂等缓存必须有界，且不得保存原始分片字节。
6. 客户端的 `agent_state` 期望值必须以服务端 `AgentPresentationState` 为真源。
7. 放弃上传必须释放服务端"每用户唯一未完成上传槽位"，15 秒上传预算是总预算且不因自动重试重置。

## 根因与修复点

| 项 | 根因 | 修复点 |
| --- | --- | --- |
| N1 | 新增 128 KiB 全局入站帧上限未与图片路径（8 MiB base64）协同 | 帧上限改为按 `infrastructure.media_resolution.max_encoded_bytes` + 信封余量推导；`WebSocketService` 默认与 `server_runtime` 注入同源 |
| N2 | `useVoiceInput` 提交后 `setCaptureState('Uploading')` 无复位；无 try/finally；`stop()` 抛错后 `finishing` 永久为真 | 重写状态机：提交后落 `Sent`/`Failed`（均可再次录音/切模式）；`cancel`/`pressOut` 全 try-finally；补快速点按、系统中断、卸载通知、启动窗口后台收尾 |
| N3 | 失败气泡的失败槽接的是播放 | `onRetry` 改接 `retryVoice`（index → MessageItem → VoiceBubble），按同一 `upload_id` 重发 |
| N4 | 验证器内硬编码 qwen 音频接口并把 `QWEN_API_KEY` 追加为核心必需密钥 | 撤销该回归（`REQUIRED_SECRET_KEYS` 回二键、删除验证器内硬编码接口）。音频接口缺失**只警告、不阻断 core**（与 `test_admin_runtime` 既有 `core_ok is True` 断言一致）；已显式配置但密钥占位符未解析仍报 error。**注意 base 两层语义不同**：校验层不阻断，但 `AudioUnderstandingSkill` 装配层会因 `register_audio_model_module` 显式失败而让业务运行时起不来（管理 Web 仍可用）——warning 文案如实说明这一点，不承诺「降级」 |
| N5 | 向量删除失败返回 `0` 伪装成功，且单次查询有上限 | 分页删除（`include=[]`）+ 无进展护栏；失败抛出；完全重置口径在 spec 中如实声明（仅本地脚本可达） |
| N6 | 驱动等待服务端从不发射的 `listening`；协议文档取值错误 | 驱动不再硬等状态，改为校验观测到的取值合法；两侧协议文档与 spec AC-27 以服务端枚举为真源更正 |
| N7 | `recordingId` 形如 `recording-<ts>-<rand>`，服务端强制 UUID 校验 | 新增 `randomUuid()`（RFC 4122 v4），录音 id 即协议 id |
| N8 | `_completed` 保存原始分片且无全局/每用户上限 | 改存 sha256 摘要（32 B/片）+ 全局 ≤256、每用户 ≤16 按最旧淘汰；失败信号投递失败记日志 |
| AC-26 | CLI 历史项对未知字段严格构造（桌面端已过滤），服务端新增字段会让整页历史静默清空 | `cli_client/network/network_client.py` 按 dataclass 字段过滤构造；补调用点级未知字段测试 |
| 体验类 | 预算在 begin 失败路径不生效、放弃路径不补 abort、ACK 后缓存键错位、录音期播服务端音频、Android 中断不可感知、`start()` 失败泄漏 expo-av 句柄 | 见下方"验证结果"对应回归测试 |

### 对齐补充（base 前进）

- **`cb4c247`（media_resolver 改构造期注入）**：接线方式以 base 为准（`UserInterface(database_manager, media_resolver)`）；本分支保留 `server_runtime.build_websocket_service(config)`（base 那侧为 `WebSocketService()`，会丢掉按配置推导的入站帧上限），并同步把两条接线测试改为断言"构造期注入"。
- **`8a1ab2d`（音频供应商身份显式化，Refs #251）**：`LLMService` 不再提供内置默认音频接口（`available_audio_models` 为空即无接口，`register_audio_model_module` 对未注册接口/缺失 prompt 直接 raise），随附 `config.json`/模板显式声明接口与音频 prompt 模板。
  - 维护者按 AC-24 字面语义把 N4 的张力**裁定为「显式失败」**（而非审查报告建议的「降级」）：提示词与供应商身份归还给认知技能/配置，缺失即报错。
  - 由于 `facade` 只要拿到 `media_resolver` 就构造 `AudioUnderstandingSkill`，「无音频配置」在**装配期**必然失败；而**校验层**仍不阻断（`test_admin_runtime` 多处 `core_ok is True`）。两层语义不同，本 PR 的 warning 文案据此改为如实描述「装配会显式失败、业务运行时无法启动」，不再使用「降级/不阻断」这类含糊表述；`test_admin_runtime` 的 AC-24 用例断言同步锁定（含「运行时无法启动」、不含「回退/降级」）。

### 复审补充（独立评审后）

- **帧上限需夹在传输层范围内**：`server_main` 不设置 uvicorn `ws_max_size`（只能在进程启动时确定），若媒体限额配到超过 uvicorn 默认 16 MiB，应用层上限会越过传输层，超限帧又回到 1009 断连。现已把上限口径统一到 `infrastructure/config/frame_limits.py`：推导结果夹紧到 `TRANSPORT_FRAME_LIMIT_BYTES`，配置校验在"媒体限额 + 信封 > 传输层上限"时给出 warning（不阻断启动），并补夹紧与告警测试。
- **N1 接线补回归测试**：`server_runtime.build_websocket_service` 抽出为独立构造点，用**非默认**媒体限额断言"配置 → 上限"未断（漏传 kwarg 会静默回落默认值，只有非默认配置能暴露）。

## 验证结果

- **server**：`pytest tests/unit tests/integration` → 1461 passed, 6 failed, 2 skipped。6 个失败均为环境/时段性：3× `test_llm_service`（无有效密钥/代理）、`test_update_login_time`（`sleep(1)` 上界 2.0 s，单独跑通过）、`test_login_stage_routing`×2（跨零点 60 s 窗口内 `elapsed=60.0` 与 `seconds_since_midnight` 冲突）。
- `pytest tests/e2e` → 4 passed, 15 skipped；`ruff` 全绿；改动文件 `black --check` 全绿；架构边界检查 10/10 PASS；单测覆盖率 50.76%（门禁 40%）。
- **app**：`tsc --noEmit` 通过；`jest` 25 suites / 164 tests 全过；改动文件 ESLint 0 error。
- **cli-client**：`pytest tests` → 156 passed。
- **变异矩阵**：对 34 个修复点逐一回退缺陷，验证回归测试确实失败 —— **34/34 全部被杀**（app 20、server 11、cli 3）。
- 本地以真实 `config/config.json` 跑配置校验：音频接口要素为 warning，业务运行时不再被其阻断（其余阻断项为不入库的 `res/tts`、`res/knowledge`、`res/sing_song` 资源缺失，属预期）。

## 未验证范围

- **AC-27 真实服务端链路**：当前可用的服务器为语音功能之前的构建（OpenAPI 无 `/media/audio/{uuid}`，`user_voice` 返回 `BAD_MESSAGE`，协调事件无 ACK），无法执行；本地又缺 `res/` 资源无法启动业务运行时。驱动、素材与命令已就绪，待有运行本分支的服务端即可执行。
- Android 真机录音权限、来电中断、弱网；DashScope 真实音频模型冒烟（`AudioModelModule.use_json` 默认值保持未动）；LRU 磁盘缓存跨重启计数。
- 管理 Web 的完全重置入口未实现（spec 已如实声明当前仅本地脚本可达）。
