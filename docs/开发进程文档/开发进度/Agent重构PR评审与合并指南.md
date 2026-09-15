# Agent 重构 PR 评审与合并指南

- 状态：**流程文档**，记录当前开放 PR 的依赖关系、建议合并顺序、跨 PR 集成点与验证口径。
- 用途：本次深模块重构的 PR 之间存在**堆叠关系**（子 PR 的分支建立在父 PR 之上），合并顺序会影响 diff 大小与冲突；本文给出可直接照做的顺序与每步操作要点。
- 相关：[实施计划](Agent重构实施计划.md)、[交接清单](Agent重构交接清单.md)、[开发守则](../开发守则.md)

## 1. 为什么需要本文

`refactor/agent` 的切片按「一个切片一个干净 PR」推进，但有些切片**真实依赖**前一个切片的代码（同一文件/同一接缝），因此采用**堆叠 PR**：子分支建立在父分支之上。

后果：

- 子 PR 的 diff 会**包含父 PR 的改动**（上游若不包含父分支，PR 的 base 只能是 `refactor/agent`）；
- 父 PR 合并后，子 PR 的 diff 会**自动缩小**（GitHub 按新 base 重算）；
- 父 PR 合并**可能让子 PR 变 `DIRTY`**（同一文件 add/add），需要把 `refactor/agent` 合进子分支解决。

## 2. 当前开放 PR（Agent 重构范围）

| PR | 切片 | Issue | 分支位置 | 文件 / 规模 |
| --- | --- | --- | --- | --- |
| [#127](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/127) | 08a 文本预处理落库 | #67 | 栈根（08 链） | 11 / +196 |
| [#128](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/128) | 08b SING 演唱行动 | #67 | 叠 127 | 17 / +436 |
| [#129](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/129) | 08c 回复生成/落库/演唱决定 | #67 | 叠 128 | 19 / +841 |
| [#130](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/130) | 10 结算与取消验收 | #69 | 叠 129 | 20 / +950 |
| [#132](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/132) | 13/14 反思接入 | #72 #73 | 叠 129 | 24 / +1284 |
| [#133](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/133) | 11a 开始思考信号 | #70 | 叠 132 | 24 / +1300 |
| [#131](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/131) | 09 MediaRef 端口提案（文档） | #68 | 叠 129 | 21 / +1028（父合并后仅剩文档） |
| [#134](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/134) | 28 过期事件清理验证 | #87 | 独立 | 2 / +94 |
| [#135](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/135) | 26 QQ 凭据维护验证 | #85 | 独立 | 2 / +79 |
| [#136](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/136) | 27 B 站事件同步验证 | #86 | 独立 | 2 / +131 |
| [#152](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/152) | 19 WorldStage | #78 | 独立 | 14 / +967 |
| [#153](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/153) | 16 首登欢迎 | #75 | 独立 | 13 / +728 |
| [#154](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/154) | 15 触摸与独立表情恢复 | #74 | 独立 | 19 / +792 |
| [#155](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/155) | 09 MediaResolver 与图片预处理 | #68 | 叠 129 | 42 / +2177 |
| [#156](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/156) | 07 生产接通与登录分流 | #66 | 叠 153 | 18 / +1104 |
| [#157](https://github.com/SheepLiu712/Agent-LuoTianyi/pull/157) | 12 明确记忆先提交后承诺 | #71 | 叠 133 | 37 / +2533 |

> 在途：**11b 慢召回多计划**（叠 157）、**15 触摸阈值配置化**（更新 154）。
> 不在本范围：#57、#123–#125（base 为 `dev`，VCPedia 相关）。

## 3. 建议合并顺序

按阶段合并，每阶段内 PR 相互独立；**父先子后**可让子 PR 的 diff 自动缩小。

1. **无依赖、只碰测试**：`#134` → `#135` → `#136`
2. **08 链（必须按父→子）**：`#127` → `#128` → `#129` → `#130` → `#132` → `#133`
3. **链的文档与子切片**：`#131`（文档，父合并后只剩文档）→ `#155`（09）→ `#157`（12）
4. **独立行为切片**（可提前合并）：`#152`（19）、`#153`（16）、`#154`（15）
5. **依赖 16 的生产接通**：`#156`（07，须在 `#153` 之后；若 `#155` 已先合，需把调用点改为 `await`，见 §4）
6. **在途**：11b（`#157` 之后）

## 4. 跨 PR 集成点（合并前必看）

- **09（#155）把 `WebSocketService.try_accept_stimulus_event` 与 `WebSocketAdapter.receive_event` 改为 `async`**；**07（#156）按当前同步契约接线**。
  → 两个 PR 谁先合，另一个都要适配：把 `websocket_service.try_accept_stimulus_event(...)` 改为 `await ...`，并复跑 `test_production_chat_reconnect_reuses_stage_after_stimulus_output` 与 stage/adapter/system/agentRuntime 套件。**合并时会由我处理**（已写入 #156 正文与进度账本）。
- **父 PR 合并后子 PR 可能变 `DIRTY`**：把 `refactor/agent` 合进子分支即可；本仓反复出现的唯一冲突是计划文档 `docs/开发进程文档/开发进度/Agent重构实施计划.md` 的 add/add（子分支带了一份旧副本），解决方式是取 `refactor/agent` 版本（`git checkout --theirs -- <path>`）。**每合并一个 PR 后我会立即同步其余分支并复跑**，保持全部 CLEAN。

## 5. 待负责人决策的两项

1. **媒体授权主体（#155 / #131）**：实现采用保守默认「引用归**上传用户**所有，跨用户解析返回 `MEDIA_UNAUTHORIZED`」。若要按角色或全局，改动很小。
2. **触摸频率阈值（#154）**：仓库无现成基线，实现曾写死 10 秒 8 次 / 30 秒 16 次；**现已改为配置驱动**（默认即上述数值），你可直接调配置或指定新默认。

## 6. 验证口径与证据

- **白名单注意**：`server/tests/conftest.py::_ACTIVE_TEST_FILES` 会把 **51/98** 个测试文件静默跳过（理由：暂由负责人统一处理）。**只跑白名单套件不足以证明没打破遗留行为**——本次即由 `tests/test_subconscious_memory.py` 抓出切片 12 的遗留回归。
  → 约定：改动遗留模块的切片，必须对相关**推迟测试**做「改动前 vs 改动后」对照（`--noconftest` 绕过跳过钩子）。各 PR 正文已附对照结果。
- **编码检查**：提交前检查新增/改动文件是否有 BOM、非法 UTF-8 或替换字符（曾修掉 `system_runtime.py` 的 BOM）。
- **每个 PR 的正文**均含：交付内容、明确不做、复审修复记录、验证命令与结果、未验证范围。评审时可只看正文 + diff 的 own 文件。

## 7. 剩余切片（依赖合并后推进）

| 切片 | Issue | 何时可做 |
| --- | --- | --- |
| 17 登录与周期提醒 claim/空闲规则 | #76 | 08 链 + 16/07 合并后（跨两条栈） |
| 18 ToyStage | #77 | 待范围确认（Issue 带 `question`） |
| 20 每日规划与活动日程 | #79 | 待范围确认（Issue 带 `question`）；且需 19 |
| 21–25 citywalk / VCPedia / 学歌 / 动态 / 日记 | #80–#84 | 19 合并后，逐个把 world 任务收口到 `WorldStage` |
| 29 旧入口与旁路清理 | #88 | 07–25 基本合并后（按真实调用图删除） |
| 30 行为不变量与架构边界验收 | #89 | 26–29 之后 |
