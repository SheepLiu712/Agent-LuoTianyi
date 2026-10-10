# `call.v1` 二进制音频帧验证

> 验证日期：2026-10-10
>
> 范围：CL-03 audio-only 部分实现
>
> 状态：候选 ADR 仍为 Proposed；本记录不是非作者 spec/ADR 验收结论

## 交付范围

本次实现共享二进制音频帧夹具，以及 Python Adapter wire codec 和 App TypeScript codec。两端使用相同的 15 字节固定头、PCM16 单声道约束、有效 golden 和稳定 codec 错误码。

decode 在读取固定头后按 `version -> route -> flags -> seq -> 声明长度与实际长度 -> 16384 字节上限 -> 非空 -> PCM 对齐` 校验；只有全部通过后才复制最多 16 KiB payload。Python codec 返回独立 `bytes`，TypeScript codec 返回独立 `Uint8Array`，并验证带偏移 view 的 `DataView` 读取。

未来可替换编码只保留窄 `AudioFrameCodec` seam。当前没有 Base64 生产实现、自动嗅探、混合编码、registry 或 plugin loader；Python 接口当前仍以 `bytes` 为编码结果，不宣称已经实现文本编码切换。

## 验证结果

| 范围 | 命令摘要 | 结果 |
| --- | --- | --- |
| Python codec | `python -m pytest tests/unit/adapter/websocket/test_call_v1_audio_codec.py -q --tb=short` | 45 passed |
| App codec | `npx jest --config jest.config.ts --runInBand __tests__/call_v1_audio_codec.test.ts` | 33 passed |
| App 全量 Jest | `npx jest --config jest.config.ts --runInBand` | 33 suites / 283 tests passed |
| App TypeScript | `npx tsc --noEmit` | passed |
| App 新增文件 ESLint | `npx eslint utils/call_protocol/types.ts utils/call_protocol/audio_codec.ts __tests__/call_v1_audio_codec.test.ts` | passed |
| Python 静态检查 | `python -m ruff check ...`、`python -m black --check ...` | passed；4 files unchanged |
| 架构边界 | `python -m pytest tests/integration/architecture/test_architecture_boundaries.py -q --tb=short` | 1 passed |
| 跨端精确验证 | 临时脚本分别调用真实 Python codec 与编译后的 TypeScript codec | 5 golden、11 fixture errors、7 error priorities 一致 |
| 文本与 diff | UTF-8/NUL/U+FFFD 检查、`git diff --check` | passed |

Python 使用 `C:/Users/Administrator/.conda/envs/agent/python.exe`。App 依赖通过现有 lockfile 执行 `npm ci --ignore-scripts` 安装，没有新增包或修改 lockfile。npm 安装器报告现有锁依赖树含 69 个 vulnerability 提示；本次未运行 `npm audit fix`，也未进行依赖安全审计。

## 已知回归限制

受影响 WebSocket 回归曾运行 `tests/integration/websocket` 与架构边界，共得到 111 passed、2 failed。两个失败均为既有 TIFF 测试内容被图像检测器识别为 JPEG，位于 `test_websocket_chat_input_contract.py`，不经过新增音频 codec；本次未修改旧媒体实现或测试。

未执行真实网络、真实 WebSocket、CallStage、控制消息、ACK/NACK、resume、取消范围、Android 真机音频或供应商测试。因此本证据只放行 audio-only 部分实现，不代表完整 CL-03、完整 F2 或上线能力。

## 仍未完成

- JSON 控制消息 schema、parser 与 endpoint
- 控制帧序号归属及 `call.switch_prepare` / `call_ws` 边界
- ACK/NACK、resume、重放与取消 envelope
- Stage 和生产 WebSocket 接线
- 非作者 spec/ADR 审核与 Issue #274 最终验收
