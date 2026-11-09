## 补充证据：圈复杂度对比（`client-godot/scripts/check_complexity.py`）

> 本条为第四轮复审（review `5379250373`）的补充证据，由 AI 辅助核查生成。最终合并决策仍应由项目维护者确认。
>
> 方法：用 head 上的 `check_complexity.py`（阈值 CC > 10，锁定依赖 `tests/requirements-complexity.txt`：gdtoolkit 4.5.0 / lizard 1.24.0 / tree-sitter 0.25.2 / tree-sitter-cpp 0.23.4）分别扫描各树；**三棵树均 0 解析错误、0 路径删除**。

### 对比一：上一轮 head `1bb36b0`（`client_godot/`）→ 本 head `f1cb9e27`（`client-godot/`）

| 指标 | `1bb36b0` | `f1cb9e27` |
|---|---|---|
| 扫描源文件 | 195 | 216 |
| 函数/单元数 | 1624 | 2287 |
| **违规（CC>10）** | **108** | **0** |
| **最高 CC** | **44** | **10** |
| 平均 CC | 3.32 | 2.93 |

- 共同路径 193 个：最高 CC 下降 80 / 持平 107 / 上升 6（均为 8→9、9→10 一级小台阶，未越限）。
- 共同单元 1494 个：下降 112 / 持平 1364 / 上升 18（全部 ≤10）。

### 对比二：隔离「gpt降低了圈复杂度」单笔（`f1cb9e27^` = `03778516` → `f1cb9e27`）

| 指标 | `03778516` | `f1cb9e27` |
|---|---|---|
| 违规（CC>10） | 122 | **0** |
| 最高 CC | 44 | **10** |
| 平均 CC | 3.39 | 2.93 |

- 共同单元 1664 个：下降 123 / 持平 1538 / 上升 3（`message_bubble._apply_ui_style` 6→9、`virtual_message_list.set_messages` 6→8、`test_system_message_presentation.run` 9→10）。
- 典型下降：
  - `tests/ui/test_login_presentation.gd` run：44 → 7
  - `tests/run_dynamics_tests.py` do_GET：44 → 9
  - `tests/run_websocket_tests.py` handler：40 → 8
  - `src/media/reply_audio.gd` append_reply_audio：38 → 10
  - `src/session/history_sync.gd` _load：35 → 10
  - `src/storage/audio_cache.gd` _valid：29 → 5
  - `native/pcm_stream_decoder.cpp` PcmStreamDecoder::append：27 → 9
  - `src/network/websocket_transport.gd` _process：27 → 9
  - `src/session/account_session.gd` _load_profile：27 → 9

### 说明

- 单元数增加来自新增文件（复杂度工具与新增测试等：对比一新增 21 条路径、对比二新增 12 条路径，均 0 删除），因此「平均 CC」不是严格同集对比；**违规清零与最高 CC 44→10** 是直接结论。
- 全部上升项均 ≤10，无新增越限。
- 结论：本轮确实显著降低了圈复杂度。结合第四轮复审 N25（该工具尚未接入任何入口），建议在合并前接入 `check.ps1` 或构建/CI，防止后续回退。
