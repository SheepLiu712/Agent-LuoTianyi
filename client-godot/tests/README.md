# Godot 测试入口

测试包括四组headless检查以及显式图形/原生窗口验收；各组脚本清单以对应check脚本为准。另有capture视觉入口。目录表示模块职责，GPU能力由运行方式区分；未列入默认组不代表过时。

现行约束与门禁见 [测试说明](../docs/testing.md)，当前整改证据见 [PR #186 整改记录](../docs/review-186.md)。历史快照中的旧文件名不再作为当前运行入口。

## 默认回归

在仓库根目录运行，使用锁定的 Godot 4.7.1 可执行文件；Python 依赖按 requirements-complexity/auth/websocket/features/visual.txt 安装到独立环境。建议通过单独APPDATA目录隔离验收数据，并保留Python依赖所在路径。

```powershell
$engine = '<Godot控制台exe绝对路径>'
$python = '<已安装测试依赖的python.exe>'
& ./client-godot/scripts/check.ps1 -Godot $engine -Python $python
& ./client-godot/scripts/check_accounts.ps1 -Godot $engine -Python $python
& ./client-godot/scripts/check_network.ps1 -Godot $engine -Python $python
& ./client-godot/scripts/check_features.ps1 -Godot $engine -Python $python
```

| 分组 | 当前内容 |
| --- | --- |
| check | 导入、强制复杂度门禁、启动、离线样板及 Godot 模块测试，含语音错误来源/去重/恢复专项；正式检查需要 Python，ImportOnly 不需要 |
| accounts | 原服务端加密互操作及6个账户协议/会话/历史/UI/Application测试；整应用用完整HTTP/WebSocket夹具 |
| network | 4个WebSocket/真实聊天/语音/触摸上报测试；不重复直接执行可靠队列测试 |
| features | 历史/图片、设置/退出/模型、动态及扩展契约测试，含确定性阅读位置专项；清单以 check_features.ps1 为准 |

各组可独立运行，不依赖前一组生成状态；首次使用新检出应先完成Godot资源导入。`check.ps1`把冷缓存导入作为独立阶段，随后才开始契约检查；`scripts/common.ps1`和各Python runner要求退出码为0、输出明确 `: PASS` 且不含 `FAIL:`/错误。每个runner为Godot进程创建一次性隔离的 `APPDATA` 与 `LOCALAPPDATA`，进程结束后清理，不能仅根据生成截图认定通过。

需要单独采集冷导入证据时运行 `check.ps1 -ImportOnly`；已有独立导入证据可用 `check.ps1 -SkipImport -Python <python.exe>` 直接运行检查；SkipImport 不跳过复杂度门禁。

合并目标可单独执行：

```powershell
& $engine --headless --path client-godot --script res://tests/media/test_reply_audio.gd
& $engine --headless --path client-godot --script res://tests/storage/test_audio_cache.gd
& $python client-godot/tests/run_dynamics_tests.py --godot $engine --script res://tests/test_dynamics.gd
& $python client-godot/tests/run_dynamics_tests.py --godot $engine --script res://tests/test_dynamics_detail.gd
```

## GPU与原生验收

### 聊天时间分组与动态加载框

`ui/test_chat_timestamps.gd` 验证相邻实际消息间隔至少 300 秒才新增居中时间气泡，首次有效消息给出时间定位；连续聊天不按累计时长重复提醒。覆盖秒/毫秒/服务端日历时间、跨日、非法时间、系统消息排除、历史分页边界、1000 条虚拟历史、阅读锚点与选区，以及两种主题和 1280×800 / 960×640。实时消息取首次到达时间，历史合并后采用历史时间；展示节点不增加业务消息或虚构 UUID。

`session/test_message_timestamps.gd` 使用实际 ChatSession 和不播放声音的媒体夹具，验证排队/送达状态不改变发送时间、服务端毫秒时间、流式首包与终包、缺失或非法时间回退，以及历史 UUID 合并保留实时正文。

```powershell
python client-godot/tests/run_feature_tests.py --godot '<Godot.exe>' --script res://tests/ui/test_chat_timestamps.gd --gpu
```

截图保存为 `artifacts/ui-redraw-client/chat-time-*.png`，使用实际聊天场景和明确标注的本地固定内容。动态专项 `ui/test_dynamics_review_actions.gd` 另验证详情加载中也没有矩形加载按钮；真实评论请求、滚到底部自动分页和失败后点击卡片重试保留，瞬时截图为 `dynamics-comments-no-loading-box.png`。这些检查不代表打包、发布或全量回归完成。

### 界面与图标风格

当前源码目录为 `client-godot`。`check.ps1` 包含 `ui/test_ui_style.gd`：验证默认扁平/SVG、四种组合、保存失败回滚、草稿关闭保护、重启恢复、虚拟列表新旧气泡及音频状态图标。

整应用验收使用已有本地 HTTP/WebSocket 夹具，隔离用户数据；不会连接生产服务。下面的命令验证设置保存、跨窗口热切换与重新启动，并将截图保存到 `client-godot/artifacts/ui-style/`：

```powershell
python client-godot/tests/run_feature_tests.py --godot 'D:/godot/godot4.7.1/godot.exe' --script res://tests/ui/test_ui_style_application.gd --gpu
```

不加 `--gpu` 可执行相同整应用行为断言，但不采集截图。加密夹具从当前 `server/src/application/user/account.py` 提取实际函数及解密异常类型。

### 其他图形验收

聊天审阅图落地的专项验收：

```powershell
python client-godot/tests/run_feature_tests.py --godot 'D:/godot/godot4.7.1/godot.exe' --script res://tests/ui/test_chat_review_layout.gd --gpu
```

该测试挂载真实 `main.tscn`，经过本地夹具登录，使用实际聊天控件、原头像/图标与 Live2D。检查 1280×800 / 960×640、扁平/清透、SVG/emoji、草稿与阅读锚点保持、分隔条及独立窗口入口；也检查图片/音量上排图标、音量滑条浮层、输入右侧方形发送图标、正常消息无发送状态占位、最新未读动态卡片及显式已读后隐藏。截图保存在 `artifacts/ui-redraw-client/`，含 `volume-popup-*` 和 `review-no-unread-*`。`flat-svg-*` / `crystal-svg-*` 是本地接口实际消息；`review-*` 使用同一产品节点树填入固定展示数据，并明确标注“布局样例 · 离线固定内容”，覆盖长文、图片和语音。不使用 `render_chat.gd` 的另绘 UI 作为产品验收。图片、窗口与系统 DPI 等其他契约仍分别运行现有测试，不据此宣称全量回归通过。

导航精简后的专项还验证聊天/动态/设置在两种风格及 SVG/emoji 下保持 64×64、导航上下头像和输入栏停止语音控件已删除、角色背景占满高度且没有底栏/手势提示；通过实际鼠标事件点击悬浮重置，确认构图恢复，并检查缩放窗口后按钮始终位于角色区右下角内侧16px。

后续精简验收使用 `run_feature_tests.py --godot <exe> --script res://tests/ui/test_dynamics_review_actions.gd --gpu`：挂载真实动态窗口与发布弹层，注入本地展示控制器，通过鼠标点击与滚轮事件验证无手动加载按钮、滚动分页及失败重试、点击缓存卡片及重复点击均刷新评论、进行中不重复请求、刷新保留草稿与当前阅读位置、失败保留内容、浏览不清未读、发布标题没有关闭按钮、底部取消仍保护草稿。覆盖扁平/清透及 1100×800 / 960×640，截图为 `dynamics-actions-*`、`dynamics-publish-clean-*` 和 `dynamics-selection-*`。共享主题契约和整应用风格专项验证三类文本控件均为 `#0078D7` 蓝底白字；聊天审阅图专项另外验证标题提示语已删除，并生成 `review-selection-*` 聊天选区截图。

必须在真实图形会话运行。以下是现行入口，按需要分别执行，不将内容缩放当作系统DPI验收。

| 脚本（相对tests） | 启动方式 | 验证内容 |
| --- | --- | --- |
| ui/test_settings_control_states.gd | run_feature_tests.py --gpu | 延迟/失败读取、重试、保存、六态开关、默认/最小及100/125/150/200%缩放；包含原最小布局Reload滚动验收 |
| ui/test_settings_export_layout.gd | 源码直接GPU运行；或同版本引擎 `--main-pack <导出PCK> --script <本脚本绝对路径>`（验证目录放置导出的DLL） | 默认/最小尺寸、隐藏页面切换后的真实尺寸及标题可见性、退出登录与侧栏对齐；release EXE不执行外部script，另用原生输入实测 |
| ui/test_login_presentation.gd | run_feature_tests.py --gpu | 纯白透明圆角、菜单、服务器取消、账号历史、记住状态、四档缩放与小屏 |
| ui/test_bubble_sizing.gd、ui/test_image_bubble_sizing.gd | 直接Godot --script，可headless或GPU | 实际排版宽度、90%上限、图片原比例及长图延迟加载锚点 |
| ui/test_logout_confirmation.gd | run_feature_tests.py --gpu | 鼠标触发、确认来源、取消焦点、实际退出提示、保存失败留稿 |
| capture_release_ui.gd | run_feature_tests.py --gpu | Application主界面、设置/日志、原生联动及合成语音样本链路 |
| capture_dynamics_ui.gd | run_dynamics_tests.py --gpu | 双栏/发布浮层/缩放及Windows独立任务栏窗口 |
| capture_voice_ui.gd | run_websocket_tests.py --gpu | 真实语音UI/角色呈现与内容缩放 |
| capture_dropdown_ui.gd | 直接Godot --script，不加--headless | 下拉边界/键盘/移动收起、透明圆角像素及内部实底 |
| avatar/test_avatar_interaction.gd | 直接Godot --script，不加--headless | 真实模型网格触摸、视线及反馈 |
| ui/test_decision_layout.gd | 直接Godot --script，不加--headless | 内嵌确认框可见范围与Esc取消 |
| ui/test_native_window_controls.gd | 直接Godot --script，并设置GODOT_TEST_PYTHON | 操作其创建的测试窗口，验证系统拖拽/缩放/三键与Alt+F4 |

Python runner入口统一带`--godot $engine --script res://tests/<脚本> --gpu`。下拉示例：`& $engine --path client-godot --script res://tests/capture_dropdown_ui.gd`。原生驱动的Python路径：`$env:GODOT_TEST_PYTHON = $python`。

显式Windows音频驱动：`& $engine --headless --audio-driver WASAPI --path client-godot --script res://tests/media/test_reply_audio.gd`。它播放合成声音并检查真实混音，不代表主观听感或公共TTS服务验收。

## 解耦与覆盖维护

- 用例不导入其他测试入口；可复用夹具只放support。各HTTP/WebSocket Handler保持领域职责，不做万能模拟服务。
- 加密夹具仍使用原服务端实际函数；WebSocket仍读取旧客户端实际wire解析器。这是跨端协议互验，不是测试启动顺序依赖。
- 场景测试只约束公开入口、ready前控件和必要语义；输入/操作提示非空，关键退出提示从实际显示状态验证，不锁定内部布局或运行时覆盖的旧默认文案。
- 失败、取消、账号隔离及资源释放场景独立创建对象/时钟/信号记录/临时目录。不要为减少文件数把不同层的测试串成依赖前置步骤的大流程。
- 移动`.gd`时一起移动其UID；删除已替代测试时删除对应UID和执行入口。现行命令同步更新，历史完成记录保留并链接本页。
- 图形检查输出在artifacts；本次整理的前后日志在artifacts/test-cleanup。未实测的平台或外部服务必须明确记录。

## 平台隔离新增验证

- `test_dependency_boundaries.py`：在账户检查执行；可独立用Python运行，检查实际代码标记（忽略注释/字符串）、依赖方向和普通消费者不创建具体平台/存储实现。
- `media/test_capability_failures.gd`：基础组，缺失解码器终止一次、队列可结束、失败重放关闭读取流。
- `application/test_platform_degradation.gd`：基础组，无认证仍可开日志、无模型明确反馈。
- `application/test_extension_contracts.gd`：功能组，本地账户夹具；三个默认接口拒绝、无假完成，真实应用切账号时上下文隔离和停止。
- `support/native_reply_audio.gd`只装配真实播放器和真实原生工厂，没有复制播放器实现。媒体消费者不再依赖隐式ClassDB创建。

本轮前后日志在`artifacts/isolation-baseline`。原生驱动等待DWM动画、只移动自身测试窗口并校验点击目标，避免桌面浮层抢占导致误判。无需打包即可进行本轮源码回归；系统DPI、Android、多屏和公共服务仍须单独验收。

## 严格圈复杂度检查

正式 `scripts/check.ps1` 在行为检查前强制执行本工具，支持 `-Python`，默认 `python`。非零退出、缺依赖、版本不符与解析错误均使入口失败；不自动安装或跳过。`-ImportOnly` 仅导入，不执行门禁。

在 `client-godot` 目录使用独立 Python 环境安装固定依赖后运行（入口拒绝不匹配的解析器版本）：

```powershell
python -m pip install -r tests/requirements-complexity.txt
python scripts/check_complexity.py
python scripts/check_complexity.py --format json
python tests/test_complexity_check.py
python tests/test_build_prompt.py
python tests/test_check_gate.py
python tests/test_review_documentation.py
```

阈值固定为 10，等于 10 合法。超限或分析失败退出码为 1；JSON 含全部单元、超限项和错误，不能用解析失败跳过文件。

覆盖 `src`、`tests` 的 GDScript，`scripts`、`tests` 的 Python/PowerShell，自有 `native` 源码与 `SConstruct`，以及 `assets` 的 shader；排除第三方插件、`native/godot-cpp`、生成物和二进制。新增自有源码放在这些目录；检查器不依赖 Git 的跟踪状态。

- GDScript 使用固定 gdtoolkit AST，支持现有内联回调语法；函数、匿名回调、属性访问器、文件/内部类初始化分别计数。
- Python 使用标准 AST，函数、回调和脚本主流程分别计数；计入 `assert`、`except`、推导式过滤条件。
- PowerShell 使用本机 AST，函数、脚本块和主流程分别计数；优先 PowerShell 7，否则使用 Windows PowerShell 5.1。后者遇到 7 的专属语法报错，不静默放行；7 的语法测试在未安装 7 时明确跳过。
- C++ 使用固定 tree-sitter-cpp 做语法结构检查、提取独立 lambda，再以固定 Lizard 默认口径计数，包含函数内条件编译分支；`GDE_EXPORT` 仅在语法解析输入中作为导出修饰宏去除，原文仍用于计数。语法检查不替代锁定工具链编译。shader 的 uniform/精度/提示声明转换为结构解析输入，仍按原文使用 Lizard 计数；结构检查不替代 Godot 编译。
- 分支、循环、条件表达式及短路操作计入；默认匹配分支不另计一次。新增辅助函数和检查器自身同样必须达标。

边界测试覆盖 10/11、短路、默认分支、嵌套函数/回调、字符串注释、属性访问器、顶层/内部类初始化、C++ lambda、解析错误与第三方排除。复杂度通过不等于行为通过，仍须执行受影响的四组回归及 GPU/系统窗口入口。
