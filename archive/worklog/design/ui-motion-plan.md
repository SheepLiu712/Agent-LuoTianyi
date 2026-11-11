# 洛天依客户端 UI 优化与动效方案（已归档）

> **归档说明（2026-11）**：本文是 2026-10-02 的动效交接方案，已不作为现行依据。
> 文中声称已落地的 `client-godot/src/ui/ui_motion.gd` **实际不存在**，全仓无 `UiMotion` 引用；
> 文中的 Godot 4.7.2 只是当时的本机开发者二进制，交付与门禁锁定 4.7.1。
> 现状与结论见 [开发工作记录](../../../client-godot/docs/WORKLOG.md) §9。

> 面向执行 agent 的交接文档。读完本文即可直接在 `client-godot` 工程里动手改 UI / 加动效，无需重新调研。
> 关联资产：
> - 登录预览网页：`tmp/login_preview.html`（全交互，可直接在浏览器打开）
> - 聊天预览网页：`tmp/chat_preview.html`（全交互）
> - 动效工具类：`client-godot/src/ui/ui_motion.gd`（已落地）

---

## 0. 背景与现状结论（调研结论，勿重复调研）

项目：`client-godot`，Godot 4.7，GDScript，31 个场景、99 个 `src` 脚本。
UI 基础设施其实已经不错：虚拟消息列表、flat/crystal 双主题、svg/emoji 双图标风格、玻璃 Shader、窗口几何记忆都已具备。

**核心短板：整个客户端此前几乎没有任何过渡动画。** 在改动前用 `rg -n "create_tween|tween_property|TRANS_|EASE_" src` 全量搜索，**只有 `src/avatar/touch_ripple.gd` 一个文件**用了 Tween。其余所有状态切换（弹窗、页面切换、窗口打开、消息出现、加载中）都是 `visible=true/false` 瞬变。

由此归纳出四类问题，方案围绕它们展开：

1. **状态无过渡** —— 所有界面切换都是 `visible` 瞬切
2. **等待无反馈** —— 网络等待只有一行静态文字，无旋转/脉冲等"活感"
3. **错误无强调** —— 错误只是状态行文字静默变化，容易被忽略
4. **窗口无生灭** —— 子窗口、弹窗、覆盖层全部瞬间出现/消失

---

## 1. 动效体系（先建地基，所有改动共用）

### 1.1 工具类 `src/ui/ui_motion.gd`（已实现）

落地动效**必须先有这个统一工具类**，禁止在各处裸写 `create_tween()`，否则时长/缓动很快失控。

提供的静态方法（全部基于 `create_tween()`，绑定节点生命周期，节点释放 tween 自动失效）：

| 方法 | 用途 | 默认时长 |
|---|---|---|
| `fade_in(node, dur, from_alpha)` | 透明度淡入 | 0.18s |
| `fade_out(node, dur)` | 透明度淡出 | 0.18s |
| `slide_fade_in(node, offset_y, dur)` | 淡入 + 上移滑入 | 0.18s |
| `pop_in(node, dur)` | 缩放 0.94→1 + 淡入（弹层入场） | 0.25s |
| `shake(node, strength, dur)` | 水平抖动（错误反馈） | 0.4s |
| `press_bounce(node, scale, dur)` | 按压回弹（按钮手感） | 0.12s |
| `spin(node, period)` | 循环旋转（加载 spinner，**返回循环 Tween，调用方负责 kill**） | 0.9s/圈 |
| `pulse(node, low, high, period)` | 循环透明度呼吸（状态指示，**循环，调用方负责 kill**） | 1.6s |
| `floaty(node, distance, period)` | 循环上下浮动（头像，**循环，调用方负责 kill**） | 3.2s |

统一时长/缓动常量：

```
DUR_INSTANT = 0.12   # 微反馈（按压、hover）
DUR_FAST    = 0.18   # 控件入场
DUR_BASE    = 0.25   # 面板、弹层
DUR_SLOW    = 0.4    # 窗口、登录转场
缓动：入场 CUBIC/EASE_OUT，回弹 BACK/EASE_OUT，淡出 CUBIC/EASE_IN
```

### 1.2 性能红线（必须遵守）

- 动画**只动 `modulate` / `position` / `scale` / `rotation`**（走渲染器变换），**不改 `size`、`custom_minimum_size`、不显隐切换**——这些会触发布局重排。
- 列表项（气泡、动态行、评论行）入场动画要做**"新到达才播"门控**：滚动历史 / 虚拟列表复用节点时**不播**（见 §3.1）。
- 循环动画（spin/pulse/floaty）在节点隐藏或状态结束时**必须 kill 并复位**（如 `_status.modulate.a = 1.0`），否则会泄漏、节点释放后报错。

---

## 2. 登录界面

参考实现：`tmp/login_preview.html`（全交互，先看它再改代码）。场景 `scenes/ui/account_view.tscn`，脚本 `src/ui/account_view.gd`。

### 2.1 视觉重绘（对齐预览图）

预览图里的样子（仅部分满足，尚未达到需求，需重做）：

- **头像**：白色圆环 + 天依蓝（#66CCFF）2px 描边 + 14px 蓝色光晕阴影 + 缓慢上下浮动。落点：主题 `LoginAvatar` 样式 + `UiMotion.floaty()`
- **登录卡片**：白色半透明卡片 + 柔和下投影（24px, y偏移12, 蓝灰色 22% 透明度）。落点：主题 `LoginSurface`
- **输入框**：聚焦时蓝色描边 + 外发光。落点：新增主题 `LoginFieldFocus` 样式 + `_setup_field_focus()` 给外层 `LoginAccountPanel` 切换样式
- **登录按钮**：蓝色渐变 + 18px 蓝色投影（浮起感）。落点：主题 `LoginPrimary` / `LoginPrimaryDisabled`
- **底部**：补了标语「和天依一起，听见世界的声音」（之前底部太空）。落点：场景 `FooterMargin` 下 `Slogan` 节点

### 2.2 交互与动效（未满足）

- **登录中**：按钮文字隐藏，显示旋转 spinner（`action_refresh.svg`），忙完恢复文字。`_set_busy_visual()` + `UiMotion.spin()`
- **登录失败**：表单水平抖动（±7px 衰减）+ 错误文字淡入。`_fail_feedback()` → `UiMotion.shake()` + `fade_in()`
- **模式切换**（登录/注册/忘记密码）：差异字段 `slide_fade_in` 错峰入场，头像/选项区淡入。`_animate_mode_change()`
- **菜单弹层（⋯）、历史账号弹层（▾）**：`pop_in` 缩放缓出入场。`_animate_popup()`
- **登录成功转场**：导航栏与工作区淡入（`src/application.gd` `_transition_to_expanded()`），启动时用 `_suppress_transition` 抑制不播

### 2.3 可交互面（预览网页已实现，供 Godot 侧继续补全）

预览网页里已做、但 **Godot 侧尚未做**的：
- 历史账号下拉点击行回填用户名（Godot 侧已有弹层，但行交互在 `_open_history()`，可补淡入）
- 服务器设置弹窗（Godot 已有 `ServerDialog`，可给弹窗加 `pop_in` 入场）
- 移除历史账号确认弹窗（`RemoveAccountDialog`，同样可加入场）

---

## 3. 聊天界面

参考实现：`tmp/chat_preview.html`（全交互）。场景 `scenes/ui/chat_view.tscn`，脚本 `src/ui/chat_view.gd`、`src/ui/virtual_message_list.gd`、`src/ui/message_bubble.gd`。

### 3.1 已落地

- **新消息气泡淡入入场**：`virtual_message_list._create_bubble()` 末尾，只对 `_note_new_arrivals()` 判定为"新到达"的消息播 `fade_in`（滚动历史不播——这是 §1.2 的门控）
- **思考状态**：`chat_view._state_changed()` 里 thinking 时 `_status` 文字 `pulse` 呼吸，结束 kill 复位（`_start_thinking_anim` / `_stop_thinking_anim`）
- **平滑滚动**：`virtual_message_list.smooth_scroll_to_latest()`，cubic 缓出、时长按距离 clamp 0.15–0.45s；滚轮/按键输入随时 kill 打断。`chat_view._to_latest()` 已切到平滑版

### 3.2 待落地（预览网页已演示，可照搬思路）

- **发送状态细分**：发送中气泡下方 `⟳ 发送中…` 旋转 → 已送达变绿色 `✓`。落点：`message_bubble.update_message()` 的 `Caption`，目前只有失败才出字
- **失败重发按钮**：`Caption` 旁加"重发"小按钮，点击调 session 重发（现在用户只能手动复制重发）
- **"正在输入"占位气泡**：回复到达前在列表底部显示跳点占位气泡，回复到达时替换。落点：`chat_view` 监听 thinking，配合虚拟列表末尾插入
- **语音条**：播放按钮按压回弹；波形进度分界柱颜色/高度渐变（现在 `message_waveform._refresh()` 逐根硬切颜色）
- **Latest/Unread 浮动按钮**：`chat_view._visible_audio()` 里 `_latest.visible` 改为淡入淡出 + 轻微上移，而非闪现

---

## 4. 子界面（动态 / 设置 / 图片 / 日志）

脚本：`dynamics_window.gd`、`dynamic_detail.gd`、`publish_overlay.gd`、`settings_window.gd`、`image_window.gd`、`unified_dropdown.gd`、`decision_dialog.gd`、`audio_settings_page.gd`。

**全部待落地**，按收益排序：

1. **窗口打开过渡（一处实现全局受益）**：`src/platform/desktop_window_host.gd open_window()` 统一加——子窗口 `modulate.a 0→1` + 内容 `scale 0.96→1` 淡入放大（0.18s）；关闭反向淡出再 hide。所有子窗口都走这里。
2. **发布覆盖层 `publish_overlay.open()`**：`Shade` 玻璃遮罩淡入（0.2s）+ 面板 y+24 滑入 `EASE_OUT_BACK` 微回弹。发布动作的仪式感，收益很高。
3. **图片窗口体验**：`image_window._zoom_by()` 缩放改 Tween 平滑过渡；加滚轮缩放（以鼠标为中心）+ 左键拖动平移——目前只能点按钮 ×0.8/×1.25 且瞬跳，是图片查看最影响体验的点。
4. **动态详情切换**：`dynamics_window.select_post()` 右侧详情淡入；选中行样式 `_select_style()` 用 tween 过渡 `border_color`/`bg_color`，不要瞬变。
5. **列表加载态**：动态列表首次加载显示骨架屏（灰圆角矩形呼吸），触底分页底部加"加载中"转圈；新插入行淡入入场。
6. **设置页切换**：`settings_window.select_page()` 四页交叉淡入淡出；保存时 `BusyBlocker` 加旋转 spinner，保存成功 `Result` 旁绿色勾缩放弹入。
7. **用量圆环动画**：`audio_settings_page` 的 `%UsageProgress.value` 用 Tween 从旧值过渡到新值（0.6s），`UsageMarker` 由 `_position_marker` 按 value 定位会自动跟随——成本极低效果直观。
8. **下拉/确认弹窗**：`unified_dropdown.open_menu()` 菜单 `scale.y 0.7→1` + 淡入（pivot 顶部）；`decision_dialog` 面板 `pop_in`。

---

## 5. 工程注意事项（执行 agent 必读）

### 5.1 文件编码（踩过的坑）

- **所有 `.tscn` / `.tres` / `.gd` 必须存为 UTF-8 无 BOM + CRLF 行尾**。
- 用 PowerShell `Set-Content -Encoding UTF8` 会写入 BOM，导致 Godot 解析 `.tres` 报 `Parse Error: Expected '['`。写文件后用下面的方法去 BOM：

```powershell
$b = [System.IO.File]::ReadAllBytes($f)
if ($b[0] -eq 239 -and $b[1] -eq 187 -and $b[2] -eq 191) {
  [System.IO.File]::WriteAllBytes($f, $b[3..($b.Length-1)])
}
```

### 5.2 Godot 可执行文件与验证

- Godot 二进制：`D:\godot\godot4.7.2\Godot_v4.7.2-stable_win64.exe`
- 改完脚本先跑解析检查（必须零错误）：

```powershell
& "D:\godot\godot4.7.2\Godot_v4.7.2-stable_win64.exe" --headless --path "D:\01restart\langchain\lty\Agent-LuoTianyi\client-godot" --check-only --quit 2>&1 | Select-String "SCRIPT ERROR|Parse"
```

- 相关测试（应 PASS）：

```powershell
-s res://tests/test_ui_scenes.gd         # 场景结构
-s res://tests/test_virtual_history.gd   # 虚拟消息列表
-s res://tests/test_reading_position.gd  # 阅读位置
-s res://tests/test_theme_contract.gd    # 主题契约
```

- **已知与改动无关的失败**：`test_account_view.gd`、`tests/ui/test_login_presentation.gd` 在**未改动的基线上也同样失败**——它们需要在线测试服务器夹具（`GODOT_TEST_SERVER`），不是本次改动引入的，不要试图"修"它们。

### 5.3 改动代码时的几个具体坑

- **字符串替换注意行尾**：工程用 CRLF。用 PowerShell 做多行替换时，匹配串里的换行必须是 `` `r`n ``，否则静默不匹配（替换"成功"但没生效）。
- **`%UniqueName` 只认场景里标了 `unique_name_in_owner = true` 的节点**：比如 `AvatarFrame`、`SubmitMargin` 没有标唯一名，脚本里要用 `%AvatarBlock.get_node("AvatarFrame")`、`%Submit.get_parent()`。
- **样式覆盖时机**：`ui_style.gd _apply_theme()` 会重建主题面板样式，会覆盖脚本在运行时 `add_theme_stylebox_override` 的样式。所以登录头像框/输入框的样式要么放主题资源里改（正解），要么把对应面板类型加进 `_apply_panel_themes()` 的适配列表。
- **登录按钮文字**：`_apply_mode()` 末尾会按模式重写 `_submit.text`，忙时 spinner 隐藏文字后要靠 `_set_busy_visual(false)` 恢复；两者别打架（已用 `if not _busy` 守卫）。
- **tween 与容器**：对由 BoxContainer 管理位置的子节点做 `position` 动画时，容器下一帧可能把它排回去（虚拟消息列表就是每帧 `_render()` 重排）。所以气泡入场**只用 `modulate` 淡入**，不用位移。

---

## 6. 实施优先级

- **P0（已完成）**：`ui_motion.gd`、气泡入场、思考状态动画、登录加载/失败反馈、登录转场、登录视觉重绘
- **P1（体验完整，建议下一批）**：发送状态图标 + 重发按钮、正在输入占位气泡、发布覆盖层入场、窗口打开过渡、图片窗口缩放/拖动
- **P2（锦上添花）**：骨架屏、用量圆环动画、设置页过渡、主题切换过渡、动态详情过渡

全部方案均基于现有节点结构，不需要改场景树骨架，主要是在对应脚本的现有状态切换点插入 `UiMotion` 调用。
