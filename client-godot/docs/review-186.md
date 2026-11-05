# PR #186 第四轮整改记录

审查基线为 `f1cb9e27689c358e58a069e6fb50c7e88c6fe00c`，Review `5379250373`，提交于 2026-10-01 20:33（北京时间）。本文记录基线之上的本地整改；不把尚未提交/推送的结果当作远端 PR 验收。

## 整改对应

| 意见 | 实现与约束 |
|---|---|
| N22 | 固定 2×2 BMP 字节样例替代不存在的保存 API；保留 PNG 输出、可解码、尺寸与像素断言。 |
| N23 | 9 个原始回复事件迁入 tests/fixtures/chat/reply_events.json；Godot 和 Python 真解析器继续共同消费。 |
| N24 | 每条详情保留待恢复目标，等请求/布局稳定后限制并应用；用户滚动取消旧目标。原实际 HTTP 断言不删除，改用状态等待并核对真实滚动范围。 |
| N25 | 基础 check 强制复杂度门禁，新增可选 -Python；ImportOnly 例外，SkipImport 不例外。依赖/解析/超限错误失败。 |
| N26 | 当前源码与使用说明统一为 0.1.5，0.1.4 仅是历史包；本轮不生成包。 |
| N27 | 现行命令使用 client-godot；旧名称仅作为明确历史说明。 |
| N28 | 现行说明进入客户端 docs，自有文档不依赖已删除根 docs 或未跟踪 docs-godot。 |
| N29 | 提供按范围的后续提交建议及准确 PR 描述草稿，不重写已推送历史，不自动提交/强推。 |
| N30 | 客户端 .gitattributes 固定 *.import 为 LF；不删除 76 个导入描述，不改全局 Git 设置。 |

## 验证状态

2026-10-01 本地工作树已完成以下验收。源码版本保持 **0.1.5**；HEAD 仍为上述复审基线，本次代码尚未提交，因此没有包含本次变更的“最终提交号”。下列结果不是远端 PR 的执行状态。

### 环境

- Windows x64，锁定引擎 `4.7.1.stable.official.a13da4feb`，可执行文件 SHA-256 为 `323f9c4cc5db674e98815cdd8e69da007d5efc779abedc8c0e42883b7fdea12a`。
- 独立测试环境 `artifacts/review-fixes-env/Scripts/python.exe`，Python 3.14.6；gdtoolkit 4.5.0、lizard 1.24.0、tree-sitter 0.25.2、tree-sitter-cpp 0.23.4，与既有 requirements 锁定版本一致。
- 图形验收为 OpenGL Compatibility，NVIDIA GeForce RTX 4070 Laptop GPU；测试使用临时 APPDATA，不读取开发者账户/缓存，不连接公共服务或付费模型。

### 正式入口

命令参数见 [测试说明](testing.md)。本地完整日志位于客户端 `artifacts/`，为未纳入提交的执行产物；它们不是源码包的必备文档。

| 入口 | 结果 | 本地日志 |
|---|---|---|
| check.ps1，原工程热缓存 | exit 0，门禁及全部后续检查实际执行 | review-186-check-audio-final.log |
| check_accounts.ps1 | exit 0，含真实 Python 解密互操作与依赖边界检查 | review-186-check_accounts-audio-final.log |
| check_network.ps1 | exit 0，四个官方场景全部执行，含真实流式语音 | review-186-check_network-audio-final.log |
| check_features.ps1 | exit 0，含原 HTTP 动态详情及新增阅读位置专项 | review-186-check_features-audio-final.log |
| check.ps1，全新无 .godot 副本 | exit 0，冷导入及全套基础检查实际执行 | review-186-check-cold-audio-final.log |

最终冷缓存副本为 `artifacts/review-186-cold-final-20261001-225049/client-godot`。冷导入发生一次官方入口已明确限定的主题纹理生成竞态，按原策略重试后通过；未删除原工程缓存、未吞掉其他错误。账户组 headless 原生窗口恢复分支打印一次 SKIP，随后 `test_application_window.gd --gpu` 已真实执行该窗口尺寸恢复断言并通过；不将 headless 跳过伪装为当次已覆盖。

### 独立质量检查

- 复杂度：220 个源码文件、2,382 个分析单元、0 超限、0 解析错误；JSON 证据为 `artifacts/review-186-complexity-audio-final.json`，阈值仍为 10。
- 复杂度工具自测：共 39 项，38 通过、1 跳过（本机无 PowerShell 7 的专项测试），不是“39 项全部无跳过通过”。
- 门禁编排 6/6、文档/版本/本地链接 5/5、构建编排 4/4、依赖边界 9/9，通过；对应日志为 `artifacts/review-186-test_*-audio-final.log`。
- 9 条共享事件与 `1bb36b0` 中历史文件逐字节一致；网络 runner 继续调用旧 Python 真解析器。Godot 的共享 JSON 消费发生在 live-chat conversation 场景，语音场景另用合成 WAV，不夸大共享样例范围。
- 76 个受 Git 管理的 `.import` 均为 LF，导入后未增加这些文件的内容差异；客户端属性只约束 `.import`，不更改全局行尾设置。

### 图形与语音专项

GPU 的原 HTTP 动态详情、新阅读位置、真实卡片操作、原生应用窗口及语音错误专项全部 exit 0，日志为 `artifacts/review-186-gpu-audio-final.log`。动态两主题在 1100×800 与 960×640 真实渲染，生成 `artifacts/review-186/reading-{flat,crystal}-{1100x800,960x640}.png`；人工抽查扁平基准与清透紧凑截图，无加载框和面板遮挡，不把固定测试评论截图当作生产会话。

## 用户追加语音日志

诊断包为 0.1.5 / Godot 4.7.1。2026-10-01 14:09:38Z（北京时间 22:09:38），失败回复的两段音频共 49,152 + 8,492 字节，已成功识别为 32 kHz、16-bit 单声道并解码 28,800 帧，随后收到 `final=true, audio_error=true` 的空音频尾包。稍后同一回复出现三次 `system_error AUDIO_ERROR`。

失败尾包来自服务端，不能据此断言为本地 WAV 解析或加载失败。三次提醒分别来自展示队列、播放完成回调、完成后再次展示；本轮将用户提示统一交给按 UUID 去重的展示队列，并以 `REMOTE_AUDIO_ERROR` 区分远端终止与本地 `AUDIO_ERROR`。诊断新增白名单 `TTS_EMPTY/TTS_STREAM_ERROR/TTS_CANCELLED` 分类及脱敏回复标识，不记录任意异常原文或用户音频。

`tests/session/test_reply_audio_errors.gd` 在修复前能复现重复提醒失败，修复后 headless/GPU 均通过，且已纳入正式基础入口。合成 WAV 覆盖日志形状、排队/正在播放时失败、零音频失败、非空失败尾包、完成前后重复尾包、首包及部分流的本地损坏/截断、一次提醒、失败缓存中止、文字保留和后续真实播放。原 PCM/混音/缓存/真实网络语音回归也通过。

**未确认项**：旧诊断包未记录服务端 error_code 或 TTS 内部 traceback，不能确定此次是超时、TTS 异常还是取消。客户端修复的是错误来源表达、重复提示及诊断可追溯性；服务端底层原因须取得同一时间段的服务端日志再处理，本轮没有修改服务端，也没有宣称 TTS 根因已解决。

## 完整回归发现的旧测试调整

- 账户测试曾让所有正常请求共用 150 ms 的专用超时夹具，冷启动触发 TIMEOUT；正常请求改用产品默认超时，150 ms + 慢服务端的 TIMEOUT 专项断言仍单独保留，产品 AccountApi 未改。
- 语音 UI 测试曾点击已按审阅删除的停止按钮；改为验证现有公开 stop_voice()，保留真实停止、混音、口型恢复及后续回复断言，不恢复旧控件。
- 草稿测试曾要求旧导航标签“动态 · 99+”；改为检查已确认的未读圆点、保留“动态”文字及精确数量 tooltip，仍等待实际状态，不增加旧导航文字。

首次失败记录保留于 `artifacts/review-186-{accounts,network,features}-initial.log`，语音修复前失败记录为 `artifacts/review-audio-errors-before.log`；这些不是最终通过证据，不隐瞒早期中止的检查。

## 后续提交与复审

建议分别提交测试/夹具修复、动态阅读位置修复、语音错误分类与去重、门禁/行尾规范、文档整理，每项注明实际验证入口。可用正文与逐项回复见 [PR 草稿](pr-186-response.md)，尚未更新远端。PR 对比以 SheepLiu712 仓库真实 dev 为准，不能以 fork 的 origin/dev 代替。提交时只选择本轮文件，不收录根 .gitignore 或服务端既有工作。

N1 的负责人确认及已延期 Issue #187–#192 不自动完成。当前时区展示语义不变。本轮不升级、打包、发布或合并；实际 PR 描述及复审回复须在相应代码提交/推送后使用最终证据。
