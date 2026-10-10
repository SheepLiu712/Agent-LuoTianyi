# `call.v1` 控制协议候选实现验证

## 范围与状态

本增量实现 `call.v1` 的共享 Draft 2020-12 schema、跨端 fixture，以及 Python / TypeScript 两端无状态 parser/encoder。ADR-0001 仍为 `Proposed`，等待非作者开发者正式审核；当前产物不是生产协议已经采用或 `call_ws` 已经可用的证明。

共享控制契约包含 16 种消息、24 个有效样例和 53 个无效样例，覆盖：

- 顶层与嵌套重复字段，包括 Unicode escaped 等值键
- 严格 UTF-8、16384-byte 上限、lone surrogate、NUL 与 U+FFFD
- 规范整数词法、UINT32、JavaScript safe integer、UUID 与 ID 长度
- transport / direction、required / unknown field、枚举与 `playback.stop` 范围关系
- `call.start.audio` 固定 `pcm_s16le / 16000 Hz / mono`
- protocol / type discriminator 的缺失、类型和未知值错误归一化

普通业务 JSON 控制帧与二进制音频帧共享每方向的 `seq` 是候选契约；ACK 推进、NACK、有限重放缓冲、resume 重放、retire payload 替换及序列状态机尚未实现。

## 技术依据与边界

可靠性机制只参考以下官方资料已经公开的机制事实：

- Socket.IO connection-state recovery 保存会话与 offset，并在有限恢复窗口中补发遗漏 packet：<https://socket.io/docs/v4/connection-state-recovery>
- ASP.NET Core 9 SignalR stateful reconnect 需要两端启用，并使用 buffer、ACK 与 replay 恢复消息：<https://learn.microsoft.com/aspnet/core/signalr/configuration#configure-stateful-reconnect>

`call.v1` 的字段、错误码、方向、序号和取消范围是本项目自研候选，不来自上述框架，也不宣称为行业标准。

当前明确不包含：生产 endpoint、ACK engine、resume replay、retire buffer、Stage 接线、生产 Base64 音频或完整通话功能。音频 codec 保留窄的未来编码替换 seam，不提供自动嗅探、registry 或 plugin loader。

## 2026-10-10 验证证据

| 范围 | 命令或方法 | 结果 |
| --- | --- | --- |
| Python control + audio | `python -m pytest tests/unit/adapter/websocket/test_call_v1_control.py tests/unit/adapter/websocket/test_call_v1_audio_codec.py -q --tb=short` | 132 passed（control 87，audio 45） |
| App control + audio | `npx jest --runInBand __tests__/call_v1_control.test.ts __tests__/call_v1_audio_codec.test.ts` | 122 passed（control 89，audio 33） |
| App 全量 | `npx jest --runInBand` | 34 suites / 372 tests passed |
| TypeScript | `npx tsc --noEmit` | passed |
| App 新文件 lint | `npx eslint utils/call_protocol/control.ts utils/call_protocol/control_types.ts __tests__/call_v1_control.test.ts` | passed |
| Python 格式与 lint | Black check + Ruff check（control 源码与测试） | passed |
| 架构边界 | `python scripts/check_architecture_boundaries.py` | B1–B10 passed |
| 跨端互操作 | 临时、未提交 Jest 驱动真实 Python 与 TypeScript parser/encoder | 77 passed：24 valid 双端 decode、规范文本/UTF-8 bytes 相同且互相 decode；53 invalid code/path 相同 |
| diff | `git diff --check` | passed，仅 Windows CRLF 提示 |

更早的相关 WebSocket 回归记录为 111 passed；当时扩大 integration 中有 2 个 TIFF fixture 既有失败。安装依赖时锁文件依赖树曾报告 69 个漏洞提示；本增量没有修改 lockfile，也没有执行 `npm audit fix`，该提示不构成本次安全审计结论。

未验证生产 WebSocket、ACK/replay 状态机、真实设备、供应商、AEC、蓝牙或性能目标。
