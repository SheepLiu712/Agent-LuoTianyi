# Godot 客户端用户可见文案清单

状态：2026-11-10，对应源码 `client-godot` 0.1.6.2。本文只登记**会渲染给用户的固定文案**，按界面和触发状态分组，逐条给出源码位置，便于改写后回填。

## 使用说明

- 表格列：`场景`、`触发/状态`、`当前文案`、`位置`、`备注`。
- 改写方式：直接替换「当前文案」列，保留「位置」列作为回填锚点；同一句在多个位置出现时逐行同步。
- 文案逐字保留源码原文；`\n` 表示实际换行，`…`、`·`、`×`、`✓`、`▾` 等符号均按原文保留。
- 同一控件有静态默认值和运行时覆盖时，分成两行，并在备注里注明。改写时优先改运行时那条；静态值只在脚本赋值前短暂可见。
- `ErrorDialog` 是统一错误弹窗，默认标题固定为「提示」，正文是表中各行的文案，确认按钮为「知道了」。
- 服务端返回或 LLM 生成的正文、用户名、动态内容、模型用途名等不属于固定文案，见第 9 节。
- 文件选择器使用 Windows 原生对话框；表中的标题、确认按钮和过滤器是 Godot 传入值，最终外观由系统绘制。

## 0. 全局与主窗口

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 主窗口标题 | 启动后 | `agentluo 0.1.6.2` | `client-godot/src/application.gd:75`、`client-godot/src/storage/release_info.gd:8`、`client-godot/release.json:1` | 模板 `%s %s`：产品名 + 版本；版本改 `release.json` 即可 |
| 左侧导航 | 常显 | `聊天` | `client-godot/scenes/main.tscn:99` | 图标按钮下方的文字 |
| 左侧导航 | 常显 | `动态` | `client-godot/scenes/main.tscn:121` | 有未读时右上角显示圆点，不显示数字 |
| 左侧导航 | 常显 | `设置` | `client-godot/scenes/main.tscn:146` | |
| 左侧导航 | 常显 | `日志` | `client-godot/scenes/main.tscn:161` | 登录前也可打开 |
| 动态导航提示 | 无未读 | `动态` | `client-godot/src/application.gd:149` | `tooltip_text` |
| 动态导航提示 | 有未读 | `动态 · %s 条未读` | `client-godot/src/application.gd:149` | `%s` 为未读数 |
| 账号存储警告 | 账号状态 `storage_error=true` | `本次登录有效，但本地登录状态未能保存或清除。下次可能需要输入密码，请查看日志。` | `client-godot/scenes/main.tscn:226` | 跨页面常驻横幅；状态恢复后隐藏 |
| 安全组件阻断 | `password_encryption.is_available()==false` | `账号与聊天功能暂不可用` | `client-godot/src/application.gd:133` | 页面左上角状态标签，运行时覆盖静态值 |
| 安全组件阻断 | 同上 | `凭据保护组件缺失，请重新解压完整程序。` | `client-godot/scenes/main.tscn:215` | 静态默认值，通常被上一行覆盖，实际不可见 |
| 安全组件阻断 | 同上，延迟弹出 | `程序文件不完整，无法启动账号与聊天功能。请重新解压或重新安装；日志和问题反馈仍可使用。` | `client-godot/src/application.gd:201` | `ErrorDialog` 正文 |
| 退出应用确认 | 有未提交草稿且点关闭 | `退出应用前请确认` | `client-godot/src/application/window_coordinator.gd:121` | 标题 |
| 退出登录确认 | 有未提交草稿且点退出登录 | `退出登录前请确认` | `client-godot/src/application/window_coordinator.gd:121` | 标题 |
| 退出/登出确认 | 有草稿 | `以下内容尚未提交：\n• ` + 草稿列表 + `\n不会自动保存或发送。` | `client-godot/src/application/window_coordinator.gd:122` | 草稿列表用换行和 `•` 拼接 |
| 退出/登出确认 | 草稿项为聊天 | `聊天输入中的未发送文字或图片` | `client-godot/src/application/window_coordinator.gd:109` | |
| 退出/登出确认 | 草稿项为设置 | `设置中的未保存修改` | `client-godot/src/application/window_coordinator.gd:113` | |
| 退出/登出确认 | 草稿项为动态 | `动态发布或评论草稿` | `client-godot/src/application/window_coordinator.gd:113` | |
| 退出/登出确认 | 确认按钮 | `放弃并继续` | `client-godot/scenes/main.tscn:208` | 退出和登出共用同一按钮文案 |
| 退出/登出确认 | 取消按钮 | `返回继续编辑` | `client-godot/scenes/main.tscn:209` | 退出和登出共用同一按钮文案 |

## 1. 登录、注册、重置与本机账号

### 1.1 登录页框架

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 左上菜单按钮 | 常显 | 无文字（图标按钮；tooltip：`菜单`） | `client-godot/scenes/ui/account_view.tscn:40` | |
| 返回登录 | 注册/重置模式 | `← 返回登录` | `client-godot/scenes/ui/account_view.tscn:101` | |
| 模式标题 | 注册模式 | `注册账号` | `client-godot/scenes/ui/account_view.tscn:108`、`client-godot/src/ui/account_view.gd:92` | 静态值会被运行时同值覆盖 |
| 模式标题 | 重置模式 | `忘记密码` | `client-godot/src/ui/account_view.gd:92` | 运行时覆盖 |
| 模式说明 | 重置模式 | `通过已使用的邀请码重置账号和密码` | `client-godot/scenes/ui/account_view.tscn:116` | 仅重置模式显示 |
| 用户名输入 | 登录/注册 | `用户名` | `client-godot/scenes/ui/account_view.tscn:144` | placeholder |
| 用户名输入 | 重置 | `新用户名` | `client-godot/src/ui/account_view.gd:94` | 运行时覆盖 placeholder |
| 本机账号按钮 | 登录模式 | 无文字（图标按钮；tooltip：`选择本机账号`） | `client-godot/scenes/ui/account_view.tscn:151` | |
| 密码输入 | 登录/注册 | `密码` | `client-godot/scenes/ui/account_view.tscn:161` | placeholder |
| 密码输入 | 重置 | `新密码` | `client-godot/src/ui/account_view.gd:95` | 运行时覆盖 placeholder |
| 确认密码 | 登录/注册 | `确认密码` | `client-godot/scenes/ui/account_view.tscn:173` | placeholder |
| 确认密码 | 重置 | `确认新密码` | `client-godot/src/ui/account_view.gd:96` | 运行时覆盖 placeholder |
| 邀请码 | 注册 | `邀请码` | `client-godot/scenes/ui/account_view.tscn:185` | placeholder |
| 邀请码 | 重置 | `已使用的邀请码` | `client-godot/src/ui/account_view.gd:99` | 运行时覆盖 placeholder |
| 已保存登录 | `remember=true` 且未手动改密码 | `已记住登录状态` | `client-godot/scenes/ui/account_view.tscn:200` | |
| 已保存登录 | 同上 | `使用密码登录` | `client-godot/scenes/ui/account_view.tscn:208` | 切回密码输入 |
| 登录选项 | 常显 | `自动登录` | `client-godot/scenes/ui/account_view.tscn:221` | 勾选框 |
| 登录选项 | 常显 | `记住登录状态` | `client-godot/scenes/ui/account_view.tscn:233` | 勾选框 |
| 提交按钮 | 登录 | `登录` | `client-godot/scenes/ui/account_view.tscn:244`、`client-godot/src/ui/account_view.gd:107` | 静态值会被运行时同值覆盖 |
| 提交按钮 | 注册 | `注册` | `client-godot/src/ui/account_view.gd:107` | 运行时覆盖 |
| 提交按钮 | 重置 | `重置账号` | `client-godot/src/ui/account_view.gd:107` | 运行时覆盖 |
| 取消请求 | 请求进行中 | `取消请求` | `client-godot/scenes/ui/account_view.tscn:264` | 仅 busy 时显示 |
| 问题反馈地址 | 打开浏览器失败后 | `https://github.com/SheepLiu712/Agent-LuoTianyi` | `client-godot/scenes/ui/account_view.tscn:271` | 只读输入框 |
| 底部链接 | 登录模式 | `忘记密码` | `client-godot/scenes/ui/account_view.tscn:290` | |
| 底部分隔 | 登录模式 | `│` | `client-godot/scenes/ui/account_view.tscn:296` | |
| 底部链接 | 登录模式 | `注册账号` | `client-godot/scenes/ui/account_view.tscn:303` | |
| 菜单项 | 点左上菜单 | `设置服务器` | `client-godot/scenes/ui/account_view.tscn:322` | |
| 菜单项 | 点左上菜单 | `日志` | `client-godot/scenes/ui/account_view.tscn:330` | |
| 菜单项 | 点左上菜单 | `问题反馈` | `client-godot/scenes/ui/account_view.tscn:338` | |

### 1.2 本机账号列表与移除

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 本机账号列表 | 无记录 | `暂无本机账号记录` | `client-godot/scenes/ui/account_view.tscn:365` | |
| 本机账号行 | 每条记录 | `{username}` | `client-godot/src/ui/account_view.gd:211` | 按钮文字，点击切换账号 |
| 移除按钮 | 每条记录 | `×`（tooltip：`移除此账号的本地记录和登录状态`） | `client-godot/scenes/ui/login_account_row.tscn:15-16` | |
| 移除确认 | 点移除 | `移除本机账号记录` | `client-godot/scenes/ui/account_view.tscn:452` | 标题 |
| 移除确认 | 点移除 | `移除“%s”的本机账号记录和已记住的登录状态？不会删除服务器账号或聊天、语音缓存。` | `client-godot/src/ui/account_view.gd:216` | `%s` 为用户名；中文引号 |
| 移除确认 | 确认按钮 | `移除记录` | `client-godot/scenes/ui/account_view.tscn:455` | |
| 移除确认 | 取消按钮 | `取消` | `client-godot/scenes/ui/decision_dialog.tscn:65` | 继承 DecisionDialog 默认值 |

### 1.3 服务器设置

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 服务器弹窗 | 点设置服务器 | `设置服务器` | `client-godot/scenes/ui/account_view.tscn:371`、`:397` | 原生窗口标题 + 页内标题 |
| 关闭按钮 | 常显 | `×` | `client-godot/scenes/ui/account_view.tscn:404` | |
| 服务器地址 | 常显 | `服务器地址` | `client-godot/scenes/ui/account_view.tscn:412` | placeholder |
| 服务器地址 | 常显 | `验证成功后才使用新服务器` | `client-godot/scenes/ui/account_view.tscn:410` | tooltip |
| 服务器状态 | 刚打开 | `验证连接成功后才使用新地址。` | `client-godot/src/ui/account_view.gd:231` | |
| 服务器状态 | 点验证 | `正在验证服务器…` | `client-godot/src/ui/account_view.gd:238` | |
| 服务器状态 | 验证失败 | `无法连接服务器，请检查网络或服务器地址。` | `client-godot/src/ui/account_view.gd:244` | |
| 恢复默认 | 常显 | `恢复默认` | `client-godot/scenes/ui/account_view.tscn:429` | |
| 取消 | 常显 | `取消` | `client-godot/scenes/ui/account_view.tscn:441` | |
| 验证并保存 | 常显 | `验证并保存` | `client-godot/scenes/ui/account_view.tscn:448` | |

### 1.4 登录状态与错误

说明：`account_view.gd` 的 `_error_text()` 同时用于页内 `%Status` 和 `ErrorDialog`。标记为空的条目不会产生可见文字。

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 登录成功 | `code=OK` | `登录成功。` | `client-godot/src/ui/account_view.gd:283` | 页内状态 |
| 退出登录 | `code=LOGGED_OUT` | `已退出登录。` | `client-godot/src/ui/account_view.gd:283` | |
| 请求中 | `code=PENDING` | `正在处理…` | `client-godot/src/ui/account_view.gd:283` | |
| 请求取消 | `code=CANCELLED` | `请求已取消。` | `client-godot/src/ui/account_view.gd:283` | |
| 认证失败 | `AUTH_REJECTED` | `用户名或密码错误，或自动登录凭据已失效。` | `client-godot/src/ui/account_view.gd:284` | 弹窗 + 页内 |
| 输入不完整 | `INVALID_INPUT` | `请填写完整信息并检查服务器地址。` | `client-godot/src/ui/account_view.gd:284` | 弹窗 + 页内 |
| 超时 | `TIMEOUT` | `连接超时，请稍后重试。` | `client-godot/src/ui/account_view.gd:285` | 弹窗 + 页内 |
| 网络错误 | `NETWORK_ERROR` | `无法连接服务器，请检查地址和网络。` | `client-godot/src/ui/account_view.gd:285` | 弹窗 + 页内 |
| 公钥/连通失败 | `PUBLIC_KEY_ERROR` | `无法连接服务器，请检查网络或服务器地址。` | `client-godot/src/ui/account_view.gd:286` | 弹窗 + 页内 |
| 加密失败 | `ENCRYPTION_ERROR` | `登录暂时无法完成，请稍后重试。` | `client-godot/src/ui/account_view.gd:286` | 弹窗 + 页内 |
| 响应异常 | `INVALID_RESPONSE` | `服务器响应异常，请稍后重试。` | `client-godot/src/ui/account_view.gd:287` | 弹窗 + 页内 |
| 凭据不可读 | `CREDENTIAL_UNAVAILABLE` | `无法读取自动登录凭据，请重新登录。` | `client-godot/src/ui/account_view.gd:287` | 弹窗 + 页内 |
| HTTP 失败 | `HTTP_ERROR` | `服务器暂时无法处理，请稍后重试。` | `client-godot/src/ui/account_view.gd:288` | 弹窗 + 页内 |
| 无保存登录 | `NO_SAVED_LOGIN` | `请使用密码登录。` | `client-godot/src/ui/account_view.gd:289` | 弹窗 + 页内 |
| 服务器更新 | `SERVER_CHANGED` | `服务器已更新。` | `client-godot/src/ui/account_view.gd:289` | |
| 正在验证 | `CHECKING_SERVER` | `正在验证服务器…` | `client-godot/src/ui/account_view.gd:289` | |
| 账号选中 | `ACCOUNT_SELECTED` | 空字符串（不显示） | `client-godot/src/ui/account_view.gd:289` | |
| 账号移除 | `ACCOUNT_REMOVED` | `本机账号记录已移除。` | `client-godot/src/ui/account_view.gd:289` | |
| 选项变更 | `OPTIONS_CHANGED` | 空字符串（不显示） | `client-godot/src/ui/account_view.gd:289` | |
| 存储错误 | `STORAGE_ERROR` | 空字符串（不显示，只进日志） | `client-godot/src/ui/account_view.gd:289` | |
| 忙 | `BUSY` | `正在处理中，请稍候。` | `client-godot/src/ui/account_view.gd:289` | 弹窗 + 页内 |
| 未知错误 | 其他 code | `操作未完成，请重试。` | `client-godot/src/ui/account_view.gd:289` | 兜底 |
| 密码字符校验 | 输入非 ASCII/控制字符 | `密码只允许英文字母、数字和英文符号，不接受中文或其他字符。` | `client-godot/src/ui/account_view.gd:7`、`:274`、`:302` | 页内 + 弹窗；输入会回退 |
| 两次密码不一致 | 注册/重置 | `两次输入的密码不一致。` | `client-godot/src/ui/account_view.gd:305-306` | 页内 + 弹窗 |
| 注册成功 | 注册完成 | `注册成功，请登录。` | `client-godot/src/ui/account_view.gd:315` | |
| 重置成功 | 重置完成 | `账号重置成功，请使用新账号登录。` | `client-godot/src/ui/account_view.gd:315` | |
| 问题反馈失败 | 外部浏览器打开失败 | `浏览器没有打开，请手动复制下面的地址。` | `client-godot/src/ui/account_view.gd:253` | 弹窗，同时显示只读地址框 |

## 2. 聊天与消息

### 2.1 聊天页框架

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 聊天页标题 | 常显 | `和天依聊聊` | `client-godot/scenes/ui/chat_view.tscn:73` | |
| 连接状态 | `phase=idle` | `未连接` | `client-godot/src/ui/chat_view.gd:271` | |
| 连接状态 | `phase=connecting` | `正在连接…` | `client-godot/src/ui/chat_view.gd:271` | |
| 连接状态 | `phase=authenticating` | `正在验证账户…` | `client-godot/src/ui/chat_view.gd:271` | |
| 连接状态 | `phase=ready` | `已连接` | `client-godot/src/ui/chat_view.gd:272` | |
| 连接状态 | `phase=reconnecting` | `连接已断开，正在重试` | `client-godot/src/ui/chat_view.gd:272` | |
| 连接状态 | `phase=auth_rejected` | `未连接` | `client-godot/src/ui/chat_view.gd:272` | 另有弹窗，见下 |
| 思考状态 | `state.thinking=true` | `天依正在想一想…` | `client-godot/src/ui/chat_view.gd:274` | 覆盖连接状态 |
| 播放状态 | `state.speaking=true` | ` · 正在播放语音` | `client-godot/src/ui/chat_view.gd:276` | 追加在状态文本后 |
| 凭据失效 | `phase=auth_rejected` 首次 | `聊天凭据已失效，请重新登录。` | `client-godot/src/ui/chat_view.gd:280` | 弹窗，每次失效只弹一次 |
| 未连接发送 | 点发送但 `phase` 为 `idle`/`auth_rejected` | `未连接，消息未发送。` | `client-godot/src/ui/chat_view.gd:161` | 弹窗；草稿保留 |

### 2.2 历史同步

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 历史状态 | `history.phase=first_loading` | `正在同步最近历史；发送的消息将暂时排队。` | `client-godot/src/ui/chat_view.gd:370` | |
| 历史状态 | `history.phase=loading` | `后台同步历史 · 已加载 %s 条` | `client-godot/src/ui/chat_view.gd:370` | `%s` 为 `history.count` |
| 历史状态 | `history.phase=skipped` | `已跳过本次历史同步。` | `client-godot/src/ui/chat_view.gd:370` | |
| 历史状态 | `history.phase=first_failed` | 空字符串（不显示状态行） | `client-godot/src/ui/chat_view.gd:370` | 由弹窗说明 |
| 历史状态 | `history.phase=failed` | 空字符串（不显示状态行） | `client-godot/src/ui/chat_view.gd:370` | 由弹窗说明 |
| 重试按钮 | `first_failed`/`failed` | `重试历史` | `client-godot/scenes/ui/chat_view.tscn:105` | |
| 跳过按钮 | `first_failed` | `跳过本次` | `client-godot/scenes/ui/chat_view.tscn:109` | |
| 首批失败 | `first_failed` | `首批历史加载失败，可重试或跳过。` | `client-godot/src/ui/chat_view.gd:374` | 弹窗 |
| 较早失败 | `failed` | `较早历史加载失败，已加载内容保留。` | `client-godot/src/ui/chat_view.gd:376` | 弹窗 |
| 历史不完整 | `history.incomplete=true` | `部分历史可能缺失。` | `client-godot/src/ui/chat_view.gd:380` | 弹窗；每次运行只弹一次 |

### 2.3 输入区与图片附件

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 输入框 | 空 | `想说什么，都可以慢慢说…` | `client-godot/scenes/ui/chat_view.tscn:205` | placeholder |
| 快捷键提示 | 常显 | `Enter 发送 · Shift + Enter 换行` | `client-godot/scenes/ui/chat_view.tscn:223` | |
| 图片按钮 | 常显 | 无文字（图标按钮；tooltip：`选择图片，也可以在输入框中 Ctrl+V 粘贴`） | `client-godot/scenes/ui/chat_view.tscn:143` | |
| 音量按钮 | 常显 | 无文字（图标按钮；tooltip：`语音音量`） | `client-godot/scenes/ui/chat_view.tscn:150` | |
| 音量浮层 | 点音量 | `语音音量` | `client-godot/scenes/ui/chat_view.tscn:247` | |
| 音量滑条 | 悬停 | `回复语音自动播放；拖到最左侧静音` | `client-godot/scenes/ui/chat_view.tscn:256` | tooltip |
| 发送按钮 | 常显 | 无文字（图标按钮；tooltip：`发送消息`） | `client-godot/scenes/ui/chat_view.tscn:217` | |
| 回到最新 | 宽屏 `size.x>=520` | `回到最新` | `client-godot/src/ui/chat_view.gd:360` | 运行时覆盖场景里的 `回到最新 ↓` |
| 回到最新 | 窄屏 `size.x<520` | `最新` | `client-godot/src/ui/chat_view.gd:360` | |
| 回到最新 | 悬停 | `回到最新消息` | `client-godot/src/ui/chat_view.gd:361` | tooltip |
| 定位未读 | 宽屏 | `定位未读` | `client-godot/src/ui/chat_view.gd:362` | |
| 定位未读 | 窄屏 | `未读` | `client-godot/src/ui/chat_view.gd:362` | |
| 定位未读 | 悬停 | `定位未读消息` | `client-godot/src/ui/chat_view.gd:363` | tooltip |
| 待发送图片 | 已选图片 | `待发送图片` | `client-godot/scenes/ui/chat_view.tscn:180` | |
| 查看附件 | 已选图片 | `查看` | `client-godot/scenes/ui/chat_view.tscn:185` | |
| 移除附件 | 已选图片 | `移除` | `client-godot/scenes/ui/chat_view.tscn:189` | |
| 图片待发送提示 | 已选图片 | `图片待发送；关闭预览后仍保留，可查看或移除。` | `client-godot/src/ui/chat_view.gd:213` | 页内状态 |
| 图片选择校验 | `IMAGE_TOO_LARGE` | `图片过大，请选择小于 6 MiB 的图片。` | `client-godot/src/ui/chat_view.gd:207` | 弹窗 |
| 图片选择校验 | `IMAGE_DIMENSIONS` | `图片尺寸过大（最多8192像素、1600万像素）。` | `client-godot/src/ui/chat_view.gd:207` | 弹窗；`8192`/`1600` 与数字之间无空格 |
| 图片选择校验 | `IMAGE_FORMAT` | `支持 PNG、JPEG、WebP 和 BMP 图片。` | `client-godot/src/ui/chat_view.gd:207` | 弹窗 |
| 图片选择校验 | `IMAGE_READ_FAILED` | `图片无法读取，请检查文件后重试。` | `client-godot/src/ui/chat_view.gd:207` | 弹窗 |
| 图片选择校验 | 其他 code | `图片格式无效或文件已损坏。` | `client-godot/src/ui/chat_view.gd:207` | 兜底 |
| 图片发送失败 | `send_image` 返回空 | `图片暂时无法发送，请检查当前连接后重试。图片已保留。` | `client-godot/src/ui/chat_view.gd:227` | 弹窗 |
| 图片文件选择 | 点图片按钮 | `选择要发送的图片` | `client-godot/scenes/ui/chat_view.tscn:260` | 原生文件对话框标题 |
| 图片文件选择 | 打开对话框 | `*.png,*.jpg,*.jpeg,*.webp,*.bmp ; 图片` | `client-godot/scenes/ui/chat_view.tscn:264` | 过滤器；系统通常显示「图片」 |

### 2.4 消息气泡与语音

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 图片气泡 | 静态默认 | `加载图片…` | `client-godot/scenes/ui/message_bubble.tscn:94` | 运行时按状态覆盖，通常只短暂可见 |
| 图片气泡 | `status=idle` | `加载图片…` | `client-godot/src/ui/message_bubble.gd:197` | 按钮文字 |
| 图片气泡 | `status=loading` | `正在下载图片…` | `client-godot/src/ui/message_bubble.gd:197` | |
| 图片气泡 | `status=ready` | `打开原图` | `client-godot/src/ui/message_bubble.gd:197` | 通常按钮隐藏，纹理可点 |
| 图片气泡 | `status=error` | `重试` | `client-godot/src/ui/message_bubble.gd:197` | |
| 图片加载失败 | 首次进入 `error` | `图片未加载，点击重试。` | `client-godot/src/ui/message_bubble.gd:199` | 弹窗 |
| 语音播放按钮 | `status=idle` | `重放` | `client-godot/src/ui/message_audio.gd:36` | |
| 语音播放按钮 | `status=playing` | `暂停` | `client-godot/src/ui/message_audio.gd:36` | |
| 语音播放按钮 | `status=paused` | `继续` | `client-godot/src/ui/message_audio.gd:36` | |
| 语音停止按钮 | 非 idle | `停止` | `client-godot/scenes/ui/message_audio.tscn:30` | |
| 语音时长 | idle | `%.1f 秒` | `client-godot/src/ui/message_audio.gd:39` | 例：`12.3 秒` |
| 语音进度 | playing/paused | `%.1f/%.1f 秒` | `client-godot/src/ui/message_audio.gd:39` | 例：`3.2/12.3 秒` |
| 语音失败 | 不可用且有 code | `这条语音无法播放。` | `client-godot/src/ui/message_audio.gd:33` | 弹窗；同一 code 只弹一次 |
| 语音静态错误 | 场景默认值 | `语音未能保存` | `client-godot/scenes/ui/message_audio.tscn:36` | 代码始终将其隐藏，当前不可见 |
| 发送失败 | 任一本机消息 `status=failed` | `发送失败` | `client-godot/src/ui/chat_view.gd:412` | 弹窗；每条只弹一次 |
| 送达不确定 | `status=uncertain` | `消息未确认送达，请刷新核实或重发。` | `client-godot/src/ui/chat_view.gd:415` | 弹窗；气泡本身隐藏 |
| 聊天错误码 | `REMOTE_AUDIO_ERROR` | `语音生成失败，可继续文字聊天。` | `client-godot/src/ui/chat_view.gd:393` | 弹窗 |
| 聊天错误码 | `AUDIO_ERROR` | `这条语音无法播放。` | `client-godot/src/ui/chat_view.gd:394` | 弹窗 |
| 聊天错误码 | `CACHE_CLEAR_FAILED` | `部分语音文件被占用，关闭后重试。` | `client-godot/src/ui/chat_view.gd:395` | 弹窗 |
| 聊天错误码 | `SEND_REJECTED` | `消息未发送，内容已保留。` | `client-godot/src/ui/chat_view.gd:396` | 弹窗 |
| 聊天错误码 | `INVALID_RESPONSE` | `服务器响应异常，请稍后重试。` | `client-godot/src/ui/chat_view.gd:397` | 弹窗 |
| 聊天错误码 | 其他非空 code | `服务器暂时无法处理，请稍后重试。` | `client-godot/src/ui/chat_view.gd:399` | 兜底；`SAVE_FAILED` 为空不弹 |

### 2.5 时间标记与角色区

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 消息时间条 | 当天消息 | `HH:MM` | `client-godot/src/ui/chat_time.gd:25-29` | 由 `Time` 生成，无中文 |
| 消息时间条 | 非当天消息 | `YYYY-MM-DD HH:MM` | `client-godot/src/ui/chat_time.gd:25-29` | 由 `Time` 生成 |
| 角色未读动态 | 有未读动态 | `%s · 未读动态` | `client-godot/src/avatar/avatar_panel.gd:24` | `%s` 为作者名；缺省作者 `洛天依` |
| 角色未读动态 | 有未读动态 | `{动态正文}` | `client-godot/src/avatar/avatar_panel.gd:25` | 卡片副标题，最多三行 |
| 角色未读动态 | 有未读动态 | `{动态正文}` | `client-godot/src/avatar/avatar_panel.gd:26` | 整个卡片 tooltip |
| 角色未读动态 | 无未读动态 | 空字符串（卡片隐藏） | `client-godot/src/avatar/avatar_panel.gd:19-22` | |
| 角色标题静态值 | 场景默认 | `未读动态` | `client-godot/scenes/avatar/avatar_panel.tscn:112` | 正常运行时会被上一行模板覆盖 |
| 重置位置 | 角色区右下 | `重置位置` | `client-godot/scenes/avatar/avatar_panel.tscn:137` | |
| 重置位置 | 悬停 | `重置角色位置与缩放` | `client-godot/scenes/avatar/avatar_panel.tscn:138` | tooltip |
| 角色资源缺失 | Live2D 加载失败 | `角色资源缺失，请重新解压完整程序。` | `client-godot/src/avatar/avatar_panel.gd:63` | 弹窗 |

## 3. 动态

### 3.1 动态列表

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 动态窗口标题 | 打开动态 | `天依的动态` | `client-godot/scenes/ui/dynamics_window.tscn:16` | 原生窗口标题 |
| 顶部未读标签 | 未读 0 | `动态` | `client-godot/src/ui/dynamics_window.gd:167` | |
| 顶部未读标签 | 未读 1–99 | `动态 · %s` | `client-godot/src/ui/dynamics_window.gd:167` | `%s` 为数字 |
| 顶部未读标签 | 未读 >99 | `动态 · 99+` | `client-godot/src/ui/dynamics_window.gd:167` | |
| 发布按钮 | 常显 | `发布动态` | `client-godot/scenes/ui/dynamics_window.tscn:49` | |
| 刷新按钮 | 常显 | `刷新` | `client-godot/scenes/ui/dynamics_window.tscn:53` | 请求中禁用，文字不变 |
| 全部已读 | 常显 | `全部已读` | `client-godot/scenes/ui/dynamics_window.tscn:57` | |
| 顶部提示条 | 有未读 | `有新的动态或评论，点击卡片查看最新评论，刷新可更新动态列表。` | `client-godot/src/ui/dynamics_window.gd:172` | 无未读时隐藏 |
| 右侧占位 | 静态默认 | `选择一条动态` | `client-godot/scenes/ui/dynamics_window.tscn:88` | 运行时会被下面几种覆盖 |
| 右侧占位 | 加载中 | `正在加载动态…` | `client-godot/src/ui/dynamics_window.gd:20` | |
| 右侧占位 | 无动态 | `还没有动态，发布第一条吧。` | `client-godot/src/ui/dynamics_window.gd:21` | |
| 右侧占位 | 加载失败且无内容 | `暂无动态` | `client-godot/src/ui/dynamics_window.gd:22` | 失败状态没有单独的措辞 |
| 右侧占位 | 有动态但未选中 | `选择左侧一条动态查看评论。` | `client-godot/src/ui/dynamics_window.gd:23` | |
| 加载失败 | 首次失败 | `暂时加载不出动态，点击重试。` | `client-godot/src/ui/dynamics_window.gd:198` | 弹窗 |
| 刷新失败 | 已有内容 | `刷新失败，点击重试。` | `client-godot/src/ui/dynamics_window.gd:198` | 弹窗 |
| 未读同步失败 | 未读请求失败 | `未读状态同步失败。` | `client-godot/src/ui/dynamics_window.gd:206` | 弹窗 |
| 动态行作者 | 每条动态 | `{author_name}` | `client-godot/src/ui/dynamics_post_row.gd:37` | 数据绑定 |
| 动态行类型 | `source_type=citywalk` | `城市漫步` | `client-godot/src/ui/dynamics_post_row.gd:3` | |
| 动态行类型 | `source_type=diary` | `天依日记` | `client-godot/src/ui/dynamics_post_row.gd:3` | |
| 动态行类型 | `source_type=song_learned` | `学会新歌` | `client-godot/src/ui/dynamics_post_row.gd:3` | |
| 动态行类型 | `source_type=system_notice` | `系统通知` | `client-godot/src/ui/dynamics_post_row.gd:3` | |
| 动态行类型 | `source_type=user_post` | `生活动态` | `client-godot/src/ui/dynamics_post_row.gd:3` | |
| 动态行类型 | 其他 | `动态` | `client-godot/src/ui/dynamics_post_row.gd:38` | 兜底 |
| 动态行元信息 | 每条动态 | `{type_label} · {created_at}` | `client-godot/src/ui/dynamics_post_row.gd:38` | 类型 + 空格 + `·` + 空格 + 服务端时间 |
| 动态行摘要 | 每条动态 | `{content}` | `client-godot/src/ui/dynamics_post_row.gd:39` | 换行替换为空格 |
| 未读圆点 | 未读 | 无文字（蓝色圆点，无 tooltip） | `client-godot/scenes/ui/dynamics_post_row.tscn:69-75` | |

### 3.2 动态详情与评论

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 详情作者 | 每条动态 | `{author_name}` | `client-godot/src/ui/dynamic_detail.gd:89` | 数据绑定 |
| 详情时间 | 每条动态 | `{created_at}` | `client-godot/src/ui/dynamic_detail.gd:90` | 原样显示服务端时间 |
| 详情正文 | 每条动态 | `{content}` | `client-godot/src/ui/dynamic_detail.gd:105` | |
| 不可评论 | `allow_comment=false` | `此动态不可评论。` | `client-godot/scenes/ui/dynamic_detail.tscn:59` | 静态默认值，按状态显示 |
| 评论输入 | 可评论 | `写下你的留言…` | `client-godot/scenes/ui/dynamic_detail.tscn:65` | placeholder |
| 发送评论 | 可评论 | `发送评论` | `client-godot/scenes/ui/dynamic_detail.tscn:72` | 发送中禁用，文字不变 |
| 回复对象标签 | 点某条评论的「回复」 | `回复 {author_name}` | `client-godot/src/ui/dynamic_detail.gd:187` | 无冒号 |
| 取消回复 | 取消回复对象后 | `已取消回复对象，文字保留为留言草稿` | `client-godot/src/ui/dynamic_detail.gd:196` | |
| 回复输入 | 回复模式 | `写下回复…` | `client-godot/scenes/ui/dynamic_detail.tscn:91` | placeholder |
| 取消回复对象 | 回复模式 | `取消回复对象` | `client-godot/scenes/ui/dynamic_detail.tscn:98` | 无对象时隐藏 |
| 发送回复 | 回复模式 | `发送回复` | `client-godot/scenes/ui/dynamic_detail.tscn:103` | |
| 发送回复 | 取消回复对象后 | `发送评论` | `client-godot/src/ui/dynamic_detail.gd:198` | 运行时覆盖静态值 |
| 评论正文 | 普通评论 | `{content}` | `client-godot/src/ui/dynamic_comment_row.gd:41` | |
| 评论正文 | 回复已知评论 | `回复 {target_author_name}：{content}` | `client-godot/src/ui/dynamic_detail.gd:181` | 全角冒号 |
| 评论正文 | 回复目标未知 | `回复 较早评论：{content}` | `client-godot/src/ui/dynamic_detail.gd:181` | 兜底 |
| 评论作者 | 每条评论 | `{author_name}` | `client-godot/src/ui/dynamic_comment_row.gd:40` | |
| 评论时间 | 0–59 秒 | `刚刚` | `client-godot/src/ui/dynamic_detail.gd:261` | |
| 评论时间 | 1–59 分钟 | `%s分钟前` | `client-godot/src/ui/dynamic_detail.gd:262` | 数字与「分钟」之间无空格 |
| 评论时间 | 1–23 小时 | `%s小时前` | `client-godot/src/ui/dynamic_detail.gd:263` | |
| 评论时间 | 1–6 天 | `%s天前` | `client-godot/src/ui/dynamic_detail.gd:264` | |
| 评论时间 | 7 天及以上 | `YYYY-MM-DD` | `client-godot/src/ui/dynamic_detail.gd:265` | 取服务端字符串前 10 位 |
| 评论时间 | 无法解析 | `{raw}` | `client-godot/src/ui/dynamic_detail.gd:251-260` | 原样显示 |
| 评论时间提示 | 悬停 | `{created_at}` | `client-godot/src/ui/dynamic_comment_row.gd:43` | tooltip |
| 回复按钮 | 每条评论 | `回复` | `client-godot/scenes/ui/dynamic_comment_row.tscn:48` | 不可评论时禁用，文字不变 |
| 评论提交失败 | `TIMEOUT`/`NETWORK_ERROR` | `发送结果不确定，请先刷新核实；草稿已保留。` | `client-godot/src/ui/dynamic_detail.gd:224` | 弹窗 |
| 评论提交失败 | `INVALID_INPUT` | `评论内容不能为空。` | `client-godot/src/ui/dynamic_detail.gd:226` | 弹窗 |
| 评论提交失败 | `BUSY` | `正在发送，请稍候。` | `client-godot/src/ui/dynamic_detail.gd:228` | 弹窗 |
| 评论提交失败 | `COMMENT_NOT_ALLOWED` | `此动态不支持评论。` | `client-godot/src/ui/dynamic_detail.gd:230` | 弹窗 |
| 评论提交失败 | `INVALID_REPLY_TARGET` | `回复对象已不存在。` | `client-godot/src/ui/dynamic_detail.gd:232` | 弹窗 |
| 评论提交失败 | 其他 | `评论失败，草稿已保留。` | `client-godot/src/ui/dynamic_detail.gd:234` | 弹窗 |
| 评论加载失败 | 任一非 OK | `评论加载失败，已保留现有内容，可重试。` | `client-godot/src/ui/dynamic_detail.gd:271` | 弹窗 |
| 评论状态标签 | 任意 | 空字符串（当前始终隐藏） | `client-godot/src/ui/dynamic_detail.gd:216`、`:218`、`:237-238` | 代码只写入空串 |

### 3.3 发布动态

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 发布浮层标题 | 打开 | `分享此刻的想法` | `client-godot/scenes/ui/publish_overlay.tscn:37` | |
| 发布输入 | 空 | `想和天依分享些什么？` | `client-godot/scenes/ui/publish_overlay.tscn:44` | placeholder |
| 取消 | 常显 | `取消` | `client-godot/scenes/ui/publish_overlay.tscn:57` | 有草稿时弹确认 |
| 发布按钮 | 常显 | `发布文字动态` | `client-godot/scenes/ui/publish_overlay.tscn:62` | 发送中禁用，文字不变 |
| 发布失败 | `TIMEOUT`/`NETWORK_ERROR` | `发布结果不确定，请先刷新核实；草稿已保留。` | `client-godot/src/ui/publish_overlay.gd:35` | 弹窗 |
| 发布失败 | `INVALID_INPUT` | `发布内容不能为空。` | `client-godot/src/ui/publish_overlay.gd:37` | 弹窗 |
| 发布失败 | 其他 | `发布失败，草稿已保留。` | `client-godot/src/ui/publish_overlay.gd:39` | 弹窗 |
| 放弃确认 | 有草稿时关闭/取消 | `放弃这条动态？` | `client-godot/scenes/ui/publish_overlay.tscn:68` | 标题 |
| 放弃确认 | 同上 | `关闭后，当前尚未发布的内容不会保留。` | `client-godot/scenes/ui/publish_overlay.tscn:69` | 正文 |
| 放弃确认 | 确认按钮 | `放弃并关闭` | `client-godot/scenes/ui/publish_overlay.tscn:70` | |
| 放弃确认 | 取消按钮 | `取消` | `client-godot/scenes/ui/decision_dialog.tscn:65` | 继承默认值 |
| 放弃确认 | 关闭按钮 | `×`（tooltip：`取消并关闭`） | `client-godot/scenes/ui/decision_dialog.tscn:33-34` | |
| 发布状态 | 任意 | 空字符串（当前始终隐藏） | `client-godot/src/ui/publish_overlay.gd:33` | 成功直接关闭浮层 |

## 4. 设置

### 4.1 设置主窗

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 设置窗口标题 | 打开 | `设置` | `client-godot/scenes/ui/settings_window.tscn:16` | 原生窗口标题 |
| 侧栏标题 | 常显 | `偏好与配置` | `client-godot/scenes/ui/settings_window.tscn:51` | |
| 页签 | 常显 | `个人资料` | `client-godot/scenes/ui/settings_window.tscn:73` | |
| 页签 | 常显 | `相处模式` | `client-godot/scenes/ui/settings_window.tscn:80` | 无偏好服务时禁用 |
| 页签 | 常显 | `模型配置` | `client-godot/scenes/ui/settings_window.tscn:87` | 无模型服务时禁用 |
| 页签 | 常显 | `缓存与导入` | `client-godot/scenes/ui/settings_window.tscn:94` | 无缓存服务时禁用 |
| 页签 | 常显 | `风格外观` | `client-godot/scenes/ui/settings_window.tscn:101` | 无样式服务时禁用 |
| 退出登录 | 常显 | `退出登录` | `client-godot/scenes/ui/settings_window.tscn:165` | |
| 关闭 | 常显 | `关闭` | `client-godot/scenes/ui/settings_window.tscn:174` | 有脏数据先弹未保存确认 |
| 保存全部修改 | 有未保存修改 | `保存全部修改` | `client-godot/scenes/ui/settings_window.tscn:178` | 干净/保存中禁用 |
| 未保存确认 | 关闭时有脏数据 | `设置尚未保存` | `client-godot/scenes/ui/settings_window.tscn:184` | 标题 |
| 未保存确认 | 同上 | `可以保存全部修改后关闭，或放弃本窗口尚未保存的修改。` | `client-godot/scenes/ui/settings_window.tscn:185` | 正文 |
| 未保存确认 | 确认按钮 | `放弃修改` | `client-godot/scenes/ui/settings_window.tscn:186` | |
| 未保存确认 | 取消按钮 | `取消` | `client-godot/scenes/ui/settings_window.tscn:187` | |
| 未保存确认 | 保存并关闭 | `保存并关闭` | `client-godot/scenes/ui/decision_dialog.tscn:54` | 此弹窗 `show_save=true`，按钮可见 |
| 保存提示 | 保存开始 | `正在保存全部修改…` | `client-godot/src/ui/settings_window.gd:145` | 常驻直到结束 |
| 保存提示 | 全部成功 | `全部修改已保存。` | `client-godot/src/ui/settings_window.gd:173` | 2 秒后消失 |
| 保存提示 | 部分失败且无逐条说明 | `已保存 %d 项；%d 项未保存，修改仍保留在本次会话。` | `client-godot/src/ui/settings_window.gd:179` | 弹窗；`%d` 为成功/失败项数 |

### 4.2 个人资料

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 页面标题 | 常显 | `个人资料` | `client-godot/scenes/ui/profile_page.tscn:44` | |
| 账号标签 | 常显 | `当前账号` | `client-godot/scenes/ui/profile_page.tscn:64` | |
| 账号名 | 无账号/未同步 | `—` | `client-godot/scenes/ui/profile_page.tscn:70`、`client-godot/src/ui/profile_page.gd:43` | 运行时也会兜底 |
| 说明 | 常显 | `支持 PNG、JPG、WebP，单张不超过 6 MB。选好后立即生效，只保存在本机。` | `client-godot/scenes/ui/profile_page.tscn:77` | |
| 选择图片 | 有账号 | `选择本地图片` | `client-godot/scenes/ui/profile_page.tscn:85` | 无用户名时禁用 |
| 恢复默认 | 有自定义头像 | `恢复默认头像` | `client-godot/scenes/ui/profile_page.tscn:90` | 无账号/无自定义头像时禁用 |
| 头像文件选择 | 点选择图片 | `选择头像图片` | `client-godot/scenes/ui/profile_page.tscn:101` | 原生文件对话框标题 |
| 头像文件选择 | 打开对话框 | `使用这张图片` | `client-godot/scenes/ui/profile_page.tscn:103` | 确认按钮 |
| 头像文件选择 | 打开对话框 | `*.png,*.jpg,*.jpeg,*.webp ; 图片` | `client-godot/scenes/ui/profile_page.tscn:107` | 过滤器 |
| 账号名 | 有用户名 | `{username}` | `client-godot/src/ui/profile_page.gd:43` | 动态 |
| 头像成功 | 应用成功 | `头像已更新。` | `client-godot/src/ui/profile_page.gd:5` | 页内绿色提示 |
| 恢复成功 | 恢复默认 | `已恢复天依头像。` | `client-godot/src/ui/profile_page.gd:6` | 页内绿色提示 |
| 头像失败 | `NO_ACCOUNT` | `登录后才能设置头像。` | `client-godot/src/ui/profile_page.gd:8` | 弹窗 |
| 头像失败 | `IMAGE_READ_FAILED` | `这张图片读不出来，换一张试试。` | `client-godot/src/ui/profile_page.gd:9` | 弹窗 |
| 头像失败 | `IMAGE_TOO_LARGE` | `图片超过 6 MB，请换一张小一点的。` | `client-godot/src/ui/profile_page.gd:10` | 弹窗；`6 MB` 中间有空格 |
| 头像失败 | `IMAGE_FORMAT` | `只支持 PNG、JPG、WebP 格式的图片。` | `client-godot/src/ui/profile_page.gd:11` | 弹窗 |
| 头像失败 | `AVATAR_WRITE_FAILED` | `头像保存失败，请重试。` | `client-godot/src/ui/profile_page.gd:12` | 弹窗 |
| 头像失败 | 其他 | `头像设置失败，请重试。` | `client-godot/src/ui/profile_page.gd:62` | 弹窗兜底 |

### 4.3 相处模式

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 页面标题 | 常显 | `和天依相处的方式` | `client-godot/scenes/ui/preferences_page.tscn:45` | |
| 关系标签 | 常显 | `关系` | `client-godot/scenes/ui/preferences_page.tscn:50` | |
| 关系输入 | 未选择 | `请选择关系` | `client-godot/scenes/ui/preferences_page.tscn:58` | placeholder；只读 |
| 关系预设 | 常显 | 无文字（图标按钮；tooltip：`选择关系预设`） | `client-godot/scenes/ui/preferences_page.tscn:68` | 只显示 chevron |
| 表达风格标签 | 常显 | `表达风格` | `client-godot/scenes/ui/preferences_page.tscn:73` | |
| 表达风格输入 | 未选择 | `请选择表达风格` | `client-godot/scenes/ui/preferences_page.tscn:81` | placeholder；只读 |
| 表达风格预设 | 常显 | 无文字（图标按钮；tooltip：`选择表达风格预设`） | `client-godot/scenes/ui/preferences_page.tscn:91` | |
| 性格关键词 | 常显 | `性格关键词` | `client-godot/scenes/ui/preferences_page.tscn:96` | |
| 性格输入 | 空 | `用逗号、顿号或换行分隔` | `client-godot/scenes/ui/preferences_page.tscn:102` | placeholder |
| 补充上下文 | 常显 | `补充上下文` | `client-godot/scenes/ui/preferences_page.tscn:108` | |
| 补充输入 | 空 | `想让天依了解的相处背景` | `client-godot/scenes/ui/preferences_page.tscn:114` | placeholder |
| 关系选项 | `friend` | `朋友` | `client-godot/src/ui/preferences_page.gd:32` | |
| 关系选项 | `confidant` | `知己` | `client-godot/src/ui/preferences_page.gd:32` | |
| 关系选项 | `idol` | `偶像` | `client-godot/src/ui/preferences_page.gd:32` | |
| 关系选项 | `partner` | `搭档` | `client-godot/src/ui/preferences_page.gd:32` | |
| 关系选项 | `family` | `家人` | `client-godot/src/ui/preferences_page.gd:32` | |
| 表达选项 | `lively` | `活泼可爱` | `client-godot/src/ui/preferences_page.gd:32` | |
| 表达选项 | `gentle` | `温柔可人` | `client-godot/src/ui/preferences_page.gd:32` | |
| 表达选项 | `quiet` | `文静恬淡` | `client-godot/src/ui/preferences_page.gd:32` | |
| 关系默认值 | 加载成功且为空 | `朋友` | `client-godot/src/session/preferences_controller.gd:89` | |
| 表达默认值 | 加载成功且为空 | `活泼可爱` | `client-godot/src/session/preferences_controller.gd:89` | |
| 加载失败 | `phase=error` | `相处偏好加载失败，请重新打开设置重试。` | `client-godot/src/ui/preferences_page.gd:82` | 3.5 秒浮层，不挡输入 |
| 保存失败 | `state.code!=OK` | `偏好保存失败，修改已保留。` | `client-godot/src/ui/preferences_page.gd:87` | 弹窗；同一错误码只弹一次 |

### 4.4 模型配置

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 页面标题 | 常显 | `LLM 模型设置` | `client-godot/scenes/ui/model_page.tscn:25` | |
| 说明 | 常显 | `服务端只规定每类调用需要的模型和能力。服务商、Base URL、模型和 Key 由你配置，Key 不会上传到服务器。` | `client-godot/scenes/ui/model_page.tscn:28` | |
| 刷新按钮 | 常显 | `刷新需求列表` | `client-godot/scenes/ui/model_page.tscn:32` | 加载/测试/保存/有脏数据时禁用 |
| 明文保存确认 | `PLAINTEXT_CONFIRMATION_REQUIRED` | `密钥保护失败` | `client-godot/scenes/ui/model_page.tscn:42` | 标题 |
| 明文保存确认 | 同上 | `Windows 未能保护 API Key。是否明确选择在本机以明文保存？默认取消保存。` | `client-godot/scenes/ui/model_page.tscn:43` | 正文 |
| 明文保存确认 | 确认按钮 | `明文保存` | `client-godot/scenes/ui/model_page.tscn:44` | |
| 明文保存确认 | 取消按钮 | `取消保存` | `client-godot/scenes/ui/model_page.tscn:45` | |
| 测试确认 | 点手动测试且 JSON 合法 | `测试可能消耗供应商额度` | `client-godot/scenes/ui/model_page.tscn:49` | 标题 |
| 测试确认 | 同上 | `将使用当前草稿发送一次固定短输入，不发送聊天历史。成功仅表示本次请求可用。` | `client-godot/scenes/ui/model_page.tscn:50` | 正文 |
| 测试确认 | 确认按钮 | `确认` | `client-godot/scenes/ui/decision_dialog.gd:6` | 未覆盖，使用默认值 |
| 测试确认 | 取消按钮 | `取消` | `client-godot/scenes/ui/model_page.tscn:51` | |
| 卡片标题 | 静态默认 | `模型用途` | `client-godot/scenes/ui/model_purpose_card.tscn:17` | 正常会被用途名覆盖 |
| 卡片标题 | 服务端无用途名 | `模型用途` | `client-godot/src/ui/model_purpose_card.gd:20` | 兜底 |
| 卡片标题 | 正常 | `{purpose.name}` | `client-godot/src/ui/model_purpose_card.gd:20` | 服务端返回 |
| 卡片说明 | 正常 | `{purpose.description}` | `client-godot/src/ui/model_purpose_card.gd:22` | 服务端返回，可能为空 |
| 启用开关 | 常显 | `使用自己的 API Key` | `client-godot/scenes/ui/model_purpose_card.tscn:20` | 关闭时隐藏字段 |
| 服务商标签 | 启用后 | `服务商名称` | `client-godot/scenes/ui/model_purpose_card.tscn:34` | |
| 地址标签 | 启用后 | `Base URL（例如 https://example.com/v1）` | `client-godot/scenes/ui/model_purpose_card.tscn:42` | |
| 密钥标签 | 启用后 | `API Key` | `client-godot/scenes/ui/model_purpose_card.tscn:50` | |
| 模型标签 | 启用后 | `模型名称` | `client-godot/scenes/ui/model_purpose_card.tscn:59` | |
| JSON 开关 | 启用后 | `声明支持 JSON 输出` | `client-godot/scenes/ui/model_purpose_card.tscn:66` | |
| thinking 开关 | 启用后 | `声明支持 thinking` | `client-godot/scenes/ui/model_purpose_card.tscn:70` | `thinking` 原文小写 |
| 参数标签 | 启用后 | `高级 JSON 参数（非流式）` | `client-godot/scenes/ui/model_purpose_card.tscn:75` | |
| 复制按钮 | 启用后 | `复制该用途配置` | `client-godot/scenes/ui/model_purpose_card.tscn:89` | |
| 测试按钮 | 有执行器 | `手动测试当前配置` | `client-godot/scenes/ui/model_purpose_card.tscn:94` | 无执行器时隐藏 |
| 调用要求 | 常显 | `调用要求：%s%s%s` | `client-godot/src/ui/model_purpose_card.gd:21` | 依次为模型类型、JSON 后缀、thinking 后缀 |
| 调用要求 | `requires_json=true` | ` / 需要 JSON` | `client-godot/src/ui/model_purpose_card.gd:21` | 前导空格 |
| 调用要求 | `requires_thinking=true` | ` / 需要 thinking` | `client-godot/src/ui/model_purpose_card.gd:21` | 前导空格 |
| 调用要求 | 模型类型 | `LLM` / `VLM` | `client-godot/src/ui/model_purpose_card.gd:21` | `model_kind` 转大写 |
| 卡片状态 | 编辑任一字段 | `有未保存的修改。` | `client-godot/src/ui/model_purpose_card.gd:66` | |
| 参数默认值 | 无参数 | `{}` | `client-godot/src/ui/model_purpose_card.gd:47` | TextEdit 内容 |
| 复制目标 | 打开下拉 | `{purpose.name}` | `client-godot/src/ui/model_purpose_card.gd:24` | 选项来自全部用途 |
| 页面状态 | 编辑任一字段 | `有未保存的修改。` | `client-godot/src/ui/model_page.gd:58` | |
| 页面状态 | 加载用途中 | `正在获取模型用途…` | `client-godot/src/ui/model_page.gd:65` | |
| 加载失败 | 加载失败或 code 非 OK | `部分配置未能恢复，可刷新重试。` | `client-godot/src/ui/model_page.gd:68`、`:73` | 弹窗 |
| 保存失败 | `INVALID_JSON` | `参数不是有效的 JSON，请检查后重试。` | `client-godot/src/ui/model_page.gd:96` | 弹窗 |
| 保存失败 | 其他 | `未保存，请重试。` | `client-godot/src/ui/model_page.gd:96` | 弹窗 |
| 复制状态 | 复制用途配置后 | `已复制为草稿；保存时按目标用途重新校验。` | `client-godot/src/ui/model_page.gd:155` | |
| 测试状态 | 测试请求中 | `正在测试…` | `client-godot/src/ui/model_page.gd:174` | |
| 测试成功 | 请求成功 | `本次请求成功；不代表已全面认证模型能力。` | `client-godot/src/ui/model_page.gd:180` | |
| 测试失败 | 字段缺失/配置无效 | `请先填写模型地址和密钥。` | `client-godot/src/ui/model_page.gd:183` | 弹窗 |
| 测试失败 | 其他 | `测试未通过，请检查服务地址和密钥后重试。` | `client-godot/src/ui/model_page.gd:183` | 弹窗 |
| 默认服务商 | 无已存配置 | `OpenAI 兼容` | `client-godot/src/session/model_settings.gd:96` | 有配置时显示配置值 |

### 4.5 风格外观

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 页面标题 | 常显 | `外观与风格` | `client-godot/scenes/ui/style_page.tscn:43` | |
| 界面风格标签 | 常显 | `界面风格` | `client-godot/scenes/ui/style_page.tscn:48` | |
| 界面风格输入 | 未选择 | `请选择界面风格` | `client-godot/scenes/ui/style_page.tscn:57` | placeholder |
| 界面风格预设 | 常显 | 无文字（图标按钮；tooltip：`选择界面风格`） | `client-godot/scenes/ui/style_page.tscn:67` | |
| 图标风格标签 | 常显 | `图标风格` | `client-godot/scenes/ui/style_page.tscn:72` | |
| 图标风格输入 | 未选择 | `请选择图标风格` | `client-godot/scenes/ui/style_page.tscn:81` | placeholder |
| 图标风格预设 | 常显 | 无文字（图标按钮；tooltip：`选择图标风格`） | `client-godot/scenes/ui/style_page.tscn:91` | |
| 界面风格值 | `flat`/未知回退 | `扁平` | `client-godot/src/ui/style_page.gd:29`、`:41` | 下拉选项同文 |
| 界面风格值 | `crystal` | `清透` | `client-godot/src/ui/style_page.gd:29`、`:41` | 下拉选项同文 |
| 图标风格值 | `svg`/未知回退 | `扁平 icon` | `client-godot/src/ui/style_page.gd:30`、`:42` | `icon` 原文小写 |
| 图标风格值 | `emoji` | `emoji` | `client-godot/src/ui/style_page.gd:30`、`:42` | 原文小写 |
| 保存失败 | 本地保存失败 | `风格保存失败，本次仍生效，重启后恢复上次设置。` | `client-godot/src/ui/style_page.gd:67` | 汇总到设置窗弹窗 |

### 4.6 缓存与导入

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 页面标题 | 常显 | `缓存与导入` | `client-godot/scenes/ui/audio_settings_page.tscn:54` | |
| 说明 | 常显 | `已接收的完整语音与历史图片保存在这台电脑上，供消息重放与查看。\n缓存按服务器和账号隔离，退出登录或重启后仍保留，不会自动清理。` | `client-godot/scenes/ui/audio_settings_page.tscn:57` | 原文含换行 |
| 导入区标题 | 常显 | `从 Python 客户端导入媒体` | `client-godot/scenes/ui/audio_settings_page.tscn:60` | |
| 导入区说明 | 常显 | `先选择 Python 客户端程序（Chat with Luotianyi.exe），再把这台电脑上可按消息对齐的语音与历史图片复制过来。\n聊天文字不在这里导入：历史正文仍从服务器读取。` | `client-godot/scenes/ui/audio_settings_page.tscn:63` | 原文含换行 |
| 客户端标签 | 常显 | `Python 客户端` | `client-godot/scenes/ui/audio_settings_page.tscn:68` | |
| 客户端路径 | 未选择 | `尚未选择` | `client-godot/scenes/ui/audio_settings_page.tscn:73` | placeholder |
| 浏览按钮 | 有导入服务 | `浏览…` | `client-godot/scenes/ui/audio_settings_page.tscn:76` | 单字符省略号 |
| 开始导入 | 有可导入媒体 | `开始导入…` | `client-godot/scenes/ui/audio_settings_page.tscn:82` | 单字符省略号 |
| 导入提示 | 常显 | `只新增不覆盖：已有缓存保持不变，Python 端的源文件也不会被移动、改名或删除。\n导入按服务器和账号分桶；若 Python 端记录的账号不同，会先提示再决定。` | `client-godot/scenes/ui/audio_settings_page.tscn:89` | 原文含换行 |
| 使用量百分比 | 初始静态 | `--%` | `client-godot/scenes/ui/audio_settings_page.tscn:124` | 扫描后覆盖 |
| 使用量状态 | 初始静态 | `存储空间扫描中` | `client-godot/scenes/ui/audio_settings_page.tscn:129` | 扫描后覆盖 |
| 使用量详情 | 初始静态 | `正在读取本账号缓存与磁盘容量…` | `client-godot/scenes/ui/audio_settings_page.tscn:145` | 异步扫描后覆盖 |
| 清理范围 | 常显 | `清理仅作用于当前服务器和账号的语音缓存；历史图片缓存不在此清理范围内。聊天文字保留，已经清理的语音将无法重放。正在播放的在线语音不会被打断。` | `client-godot/scenes/ui/audio_settings_page.tscn:147` | |
| 清理标签 | 常显 | `清理` | `client-godot/scenes/ui/audio_settings_page.tscn:152` | 与天数、后缀拼成一句 |
| 清理天数 | 默认值 | `30` | `client-godot/scenes/ui/audio_settings_page.tscn:159` | 显示为「清理 30 天之前的缓存」 |
| 清理后缀 | 常显 | `天之前的缓存` | `client-godot/scenes/ui/audio_settings_page.tscn:163` | |
| 天数提示 | 常显 | `可自由输入天数；0 表示全部缓存。` | `client-godot/scenes/ui/audio_settings_page.tscn:165` | |
| 天数提示 | 悬停 | `依据本机缓存保存时间；旧记录使用文件修改时间，时间未知则保留。` | `client-godot/scenes/ui/audio_settings_page.tscn:166` | Label tooltip，是否触发取决于鼠标过滤 |
| 清理按钮 | 非导入中 | `清理本账号语音缓存…` | `client-godot/scenes/ui/audio_settings_page.tscn:173` | |
| 重新扫描 | 非扫描中 | `重新扫描` | `client-godot/scenes/ui/audio_settings_page.tscn:178` | |
| 底部提示 | 常显 | `缓存清理是单独操作，不会随“保存全部修改”自动执行。` | `client-godot/scenes/ui/audio_settings_page.tscn:186` | 中文弯引号 |
| 清理确认 | 点清理 | `清理语音缓存` | `client-godot/scenes/ui/audio_settings_page.tscn:190` | 标题 |
| 清理确认 | 点清理（静态默认） | `清理当前服务器、本账号保存的全部语音？\n聊天文字保留；已清理的语音将无法重放。` | `client-godot/scenes/ui/audio_settings_page.tscn:191` | 运行时会被下面两行覆盖 |
| 清理确认 | 清理全部（天数 0） | `清理当前服务器、本账号的全部语音缓存？\n聊天文字保留；已清理语音无法重放。本地重放将停止，在线声音继续。` | `client-godot/src/ui/audio_settings_page.gd:168` | 运行时正文 |
| 清理确认 | 清理指定天数 | `清理当前服务器、本账号 %s 天之前保存的语音缓存？\n聊天文字保留；已清理语音无法重放。本地重放将停止，在线声音继续。` | `client-godot/src/ui/audio_settings_page.gd:168` | `%s` 为天数 |
| 清理确认 | 确认按钮 | `清理` | `client-godot/scenes/ui/audio_settings_page.tscn:192` | |
| 清理确认 | 取消按钮 | `取消` | `client-godot/scenes/ui/audio_settings_page.tscn:193` | |
| 导入确认 | 点开始导入 | `导入媒体` | `client-godot/scenes/ui/audio_settings_page.tscn:196` | 标题 |
| 导入确认 | 点开始导入（静态默认） | `把本机 Python 客户端保存的语音与历史图片复制到当前账号？` | `client-godot/scenes/ui/audio_settings_page.tscn:197` | 运行时会被下面两条覆盖 |
| 导入确认 | 普通确认 | `把 Python 客户端保存的语音与历史图片复制到当前账号？\n\n只新增、不覆盖：已有缓存保持不变，源文件保留。` | `client-godot/src/ui/audio_settings_page.gd:202` | 运行时正文 |
| 导入确认 | 账号/服务器不一致 | `%s\n\n注意：Python 客户端记录的是 %s @ %s，与当前登录不同；媒体仍会写入当前账号。` | `client-godot/src/ui/audio_settings_page.gd:207` | 依次为基础正文、用户名、服务器地址 |
| 导入确认 | 缺用户名 | `未知账号` | `client-godot/src/ui/audio_settings_page.gd:208` | 兜底 |
| 导入确认 | 缺服务器 | `未知服务器` | `client-godot/src/ui/audio_settings_page.gd:208` | 兜底 |
| 导入确认 | 确认按钮 | `开始导入` | `client-godot/scenes/ui/audio_settings_page.tscn:198` | |
| 导入确认 | 取消按钮 | `取消` | `client-godot/scenes/ui/audio_settings_page.tscn:199` | |
| 客户端文件选择 | 点浏览 | `选择 Python 客户端程序` | `client-godot/scenes/ui/audio_settings_page.tscn:202` | 原生文件对话框标题 |
| 客户端文件选择 | 打开对话框 | `使用这个程序` | `client-godot/scenes/ui/audio_settings_page.tscn:204` | 确认按钮 |
| 客户端文件选择 | 打开对话框 | `*.exe ; Windows 可执行文件` | `client-godot/scenes/ui/audio_settings_page.tscn:207` | 过滤器 |
| 扫描结果 | 扫描成功 | `已识别客户端：语音 %d 条，图片 %d 张。` | `client-godot/src/ui/audio_settings_page.gd:110` | `%d` 为语音/图片数 |
| 扫描结果 | 有未匹配图片 | `另有 %d 张图片无法按消息匹配或格式不支持，不会导入。` | `client-godot/src/ui/audio_settings_page.gd:113` | 追加到扫描结果 |
| 扫描结果 | 缺目录 | ` 缺少：%s。` | `client-godot/src/ui/audio_settings_page.gd:120` | 前导空格；`%s` 为目录名 |
| 扫描结果 | 缺语音目录 | `语音目录` | `client-godot/src/ui/audio_settings_page.gd:116` | 填入上一行 |
| 扫描结果 | 缺图片目录 | `图片目录` | `client-godot/src/ui/audio_settings_page.gd:118` | 填入上一行 |
| 扫描结果 | 无媒体 | ` 没有可导入的媒体。` | `client-godot/src/ui/audio_settings_page.gd:122` | 前导空格 |
| 扫描失败 | `TARGET_INVALID` | `不是可识别的客户端目录，请重新选择程序。` | `client-godot/src/ui/audio_settings_page.gd:129` | 弹窗 |
| 扫描失败 | `TARGET_MISSING` 且已选路径 | `目标目录不存在，请重新选择程序。` | `client-godot/src/ui/audio_settings_page.gd:131` | 弹窗 |
| 扫描失败 | `TARGET_MISSING` 且未选路径 | `尚未选择 Python 客户端程序。` | `client-godot/src/ui/audio_settings_page.gd:131` | 弹窗 |
| 扫描失败 | 其他 | `导入暂不可用，请重新选择程序。` | `client-godot/src/ui/audio_settings_page.gd:133` | 弹窗兜底 |
| 账号不一致提示 | 选中客户端后 | `\n注意：Python 客户端记录的账号/服务器与当前登录不同，导入前会再次确认。` | `client-godot/src/ui/audio_settings_page.gd:155` | 追加到扫描结果；前导换行 |
| 清理天数非法 | 非有限/负数/超大 | `请输入有效的非负整数天数。` | `client-godot/src/ui/audio_settings_page.gd:162` | 弹窗 |
| 导入中清理 | 导入进行中 | `正在导入媒体，请等导入完成后再清理。` | `client-godot/src/ui/audio_settings_page.gd:165` | 页内状态 |
| 清理中 | 请求中 | `正在清理…` | `client-godot/src/ui/audio_settings_page.gd:177` | |
| 清理成功 | 全部清理 | `已清理本账号全部语音缓存。聊天文字已保留。` | `client-godot/src/ui/audio_settings_page.gd:184` | |
| 清理成功 | 指定天数 | `已清理本账号 %s 天之前的语音缓存。聊天文字已保留。` | `client-godot/src/ui/audio_settings_page.gd:184` | `%s` 为天数 |
| 清理失败 | 请求失败 | `部分语音文件被占用，关闭后重试。` | `client-godot/src/ui/audio_settings_page.gd:187` | 弹窗 |
| 导入开始 | 点击确认后 | `正在导入 Python 客户端媒体…` | `client-godot/src/ui/audio_settings_page.gd:216` | |
| 导入进度 | 导入中 | `正在导入 %d / %d（语音 %d / %d，图片 %d / %d）…` | `client-godot/src/ui/audio_settings_page.gd:230` | 依次为总进度、语音进度、图片进度 |
| 导入完成 | `imported>0` | `已按需导入 %d 条语音。` | `client-godot/src/ui/audio_settings_page.gd:246` | `%d` 为数量 |
| 导入不可用 | `STORAGE_UNAVAILABLE` | `缓存目录不可用，请先登录后再导入。` | `client-godot/src/ui/audio_settings_page.gd:256`、`:270` | 弹窗 |
| 导入不可用 | 其他 | `导入暂不可用，请重新选择 Python 客户端程序。` | `client-godot/src/ui/audio_settings_page.gd:257` | 弹窗 |
| 导入无媒体 | `SOURCE_EMPTY` | `选中的客户端里没有可导入的媒体文件。` | `client-godot/src/ui/audio_settings_page.gd:266` | 弹窗 |
| 导入完成 | 无失败 | `已处理 %d 条（语音 %d、图片 %d）：导入 %d 条，跳过 %d 条，失败 %d 条。` | `client-godot/src/ui/audio_settings_page.gd:272` | 页内摘要 |
| 导入完成 | 有失败 | `部分文件未导入，已成功的内容会保留；未成功的条目会在翻看历史时自动重试。` | `client-godot/src/ui/audio_settings_page.gd:278` | 弹窗，替换计数摘要 |
| 空间扫描 | 刷新时 | `存储空间扫描中` | `client-godot/src/ui/audio_settings_page.gd:294` | |
| 空间百分比 | 已用 0 | `0%` | `client-godot/src/ui/audio_settings_page.gd:306` | |
| 空间百分比 | 比例小于 0.01% | `<0.01%` | `client-godot/src/ui/audio_settings_page.gd:306` | |
| 空间百分比 | 正常 | `%.2f%%` | `client-godot/src/ui/audio_settings_page.gd:306` | 保留两位小数 |
| 空间百分比 | 容量未知 | `--%` | `client-godot/src/ui/audio_settings_page.gd:306` | |
| 空间状态 | 容量已知 | `占所在磁盘空间` | `client-godot/src/ui/audio_settings_page.gd:307` | |
| 空间状态 | 容量未知 | `存储数据暂不可用` | `client-godot/src/ui/audio_settings_page.gd:307` | |
| 空间详情 | 扫描完成 | `本账号语音缓存：%s\n\n所在磁盘总容量：%s\n可用容量：%s` | `client-godot/src/ui/audio_settings_page.gd:308` | 三个容量字符串 |
| 容量格式化 | 字节数为负 | `无法读取` | `client-godot/src/ui/audio_settings_page.gd:321` | |
| 容量格式化 | 小于 1024 字节 | `%s bytes` | `client-godot/src/ui/audio_settings_page.gd:322` | |
| 容量格式化 | 大于等于 1024 字节 | `%.2f %s` | `client-godot/src/ui/audio_settings_page.gd:326` | `%s` 为 KiB/MiB/GiB/TiB/PiB |
| 容量单位 | 依次尝试 | `KiB` / `MiB` / `GiB` / `TiB` / `PiB` | `client-godot/src/ui/audio_settings_page.gd:324` | 超出后回退 `%s bytes` |
| 客户端路径 | 已选择 | `{path}` | `client-godot/src/ui/audio_settings_page.gd:92` | 输入框内容 |
| 客户端路径 | 悬停 | `{path}` | `client-godot/src/ui/audio_settings_page.gd:93` | 与输入框相同的 tooltip |

## 5. 日志窗口

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 日志窗口标题 | 打开 | `客户端日志 · agentluo 0.1.6.2` | `client-godot/src/ui/log_window.gd:31`、`client-godot/src/storage/release_info.gd:8` | 模板 `客户端日志 · %s %s` |
| 启动记录 | 当前启动在列表中 | `{started} · 本次启动` | `client-godot/src/ui/log_window.gd:100-104` | `{started}` 为启动时间 |
| 启动记录 | 非当前、运行中 | `{started} · 运行中` | `client-godot/src/ui/log_window.gd:106` | |
| 启动记录 | 非当前、异常结束 | `{started} · 未正常结束` | `client-godot/src/ui/log_window.gd:106` | |
| 启动记录 | 非当前、已关闭 | `{started}` | `client-godot/src/ui/log_window.gd:102` | 无后缀 |
| 启动记录 | 当前启动未能保存 | `本次启动（未能保存） · 本次启动` | `client-godot/src/ui/log_window.gd:100`、`:104` | 两段后缀叠加，疑似重复 |
| 级别下拉 | 默认 | `全部级别` | `client-godot/src/ui/log_window.gd:43` | |
| 级别选项 | 各级别 | `DEBUG` / `INFO` / `WARN` / `ERROR` | `client-godot/src/ui/log_window.gd:43` | 原文大写 |
| 类别下拉 | 默认 | `全部类别` | `client-godot/src/ui/log_window.gd:44` | |
| 类别选项 | `error` | `错误` | `client-godot/src/storage/log_schema.gd:7` | |
| 类别选项 | `warning` | `警告` | `client-godot/src/storage/log_schema.gd:7` | |
| 类别选项 | `info` | `信息` | `client-godot/src/storage/log_schema.gd:7` | |
| 类别选项 | `debug` | `调试` | `client-godot/src/storage/log_schema.gd:7` | |
| 类别选项 | `access` | `访问` | `client-godot/src/storage/log_schema.gd:8` | |
| 类别选项 | `security` | `安全` | `client-godot/src/storage/log_schema.gd:8` | |
| 类别选项 | `performance` | `性能` | `client-godot/src/storage/log_schema.gd:8` | |
| 类别选项 | `transaction` | `事务` | `client-godot/src/storage/log_schema.gd:9` | |
| 类别选项 | `runtime` | `运行` | `client-godot/src/storage/log_schema.gd:9` | |
| 模块下拉 | 默认 | `全部模块` | `client-godot/src/ui/log_window.gd:48` | |
| 模块选项 | 各模块 | `app` / `account` / `network` / `message` / `audio` / `cache` / `history` / `settings` / `dynamics` / `engine` | `client-godot/src/storage/log_schema.gd:20` | 模块 ID 原文直接显示 |
| 归属下拉 | 默认 | `全部归属` | `client-godot/src/ui/log_window.gd:52` | |
| 归属选项 | `client` | `客户端` | `client-godot/src/storage/log_schema.gd:15` | |
| 归属选项 | `network` | `网络链路` | `client-godot/src/storage/log_schema.gd:15` | |
| 归属选项 | `server` | `服务端` | `client-godot/src/storage/log_schema.gd:15` | |
| 归属选项 | `upstream` | `上游服务` | `client-godot/src/storage/log_schema.gd:16` | |
| 归属选项 | `none` | `无` | `client-godot/src/storage/log_schema.gd:16` | |
| 归属选项 | `unknown` | `未知` | `client-godot/src/storage/log_schema.gd:16` | |
| 搜索框 | 空 | `搜索时间、活动或错误码` | `client-godot/scenes/ui/log_window.tscn:63` | placeholder |
| 跟随最新 | 默认选中 | `跟随最新` | `client-godot/scenes/ui/log_window.tscn:78` | |
| 复制按钮 | 常显 | `复制显示记录` | `client-godot/scenes/ui/log_window.tscn:84` | |
| 导出按钮 | 常显 | `导出完整诊断 ZIP` | `client-godot/scenes/ui/log_window.tscn:88` | |
| 状态标签 | 无分类计数 | `共 %s 条记录；筛选只影响显示，导出包含整次启动。` | `client-godot/src/ui/log_window.gd:136` | `%s` 为条数 |
| 状态标签 | 有分类计数 | `共 %s 条记录（%s）；筛选只影响显示，导出包含整次启动。` | `client-godot/src/ui/log_window.gd:138` | 第二个 `%s` 为分类计数 |
| 分类计数 | 某类有记录 | `%s %s` + ` / ` 分隔 | `client-godot/src/ui/log_window.gd:135`、`:138` | 类别标签 + 空格 + 数量 |
| 未知事件说明 | 事件不在注册表 | `客户端活动` | `client-godot/src/storage/log_schema.gd:306` | 日志行 message 的兜底 |
| 导出成功 | 导出完成 | `所选启动的完整诊断已导出（未上传）。` | `client-godot/src/ui/log_window.gd:83` | 状态标签 |
| 导出文件名 | 点导出 | `agentluo-diagnostics-{run_id}.zip` | `client-godot/src/ui/log_window.gd:79` | `run_id` 完整显示 |
| 保存过滤器 | 打开导出对话框 | `*.zip ; ZIP 诊断包` | `client-godot/scenes/ui/log_window.tscn:99` | 系统通常显示「ZIP 诊断包」 |
| 复制失败 | 剪贴板失败 | `复制失败，请手动选择文本。` | `client-godot/src/ui/log_window.gd:75` | 弹窗 |
| 导出失败 | 文件已存在/不可写 | `导出失败：目标文件已存在或不可写，请换一个路径。` | `client-godot/src/ui/log_window.gd:86` | 弹窗 |
| 归档不完整 | 写入失败 | `归档可能不完整，当前窗口仍可查看本次记录。` | `client-godot/src/ui/log_window.gd:93` | 弹窗 |
| 归档不完整 | 读取到不完整归档 | `归档可能不完整，当前窗口仍可查看本次记录。` | `client-godot/src/ui/log_window.gd:146` | 与上一行同文，触发点不同 |

## 6. 通用弹窗、提示与下拉

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 错误弹窗标题 | 默认 | `提示` | `client-godot/src/ui/error_dialog.gd:15`、`:47` | 所有调用均未覆盖 |
| 错误弹窗关闭 | 常显 | `×`（tooltip：`关闭`） | `client-godot/scenes/ui/error_dialog.tscn:35-36` | |
| 错误弹窗确认 | 常显 | `知道了` | `client-godot/scenes/ui/error_dialog.tscn:54` | |
| 通用确认弹窗 | 默认确认 | `确认` | `client-godot/src/ui/decision_dialog.gd:6`、`client-godot/scenes/ui/decision_dialog.tscn:60` | 可被实例覆盖 |
| 通用确认弹窗 | 默认取消 | `取消` | `client-godot/src/ui/decision_dialog.gd:7`、`client-godot/scenes/ui/decision_dialog.tscn:65` | 可被实例覆盖 |
| 通用确认弹窗 | 保存并关闭 | `保存并关闭` | `client-godot/scenes/ui/decision_dialog.tscn:54` | 默认隐藏 |
| 通用确认弹窗 | 关闭 | `×`（tooltip：`取消并关闭`） | `client-godot/scenes/ui/decision_dialog.tscn:33-34` | |
| 草稿窗口放弃确认 | 关闭有未保存内容的草稿窗 | `放弃未保存的修改？` | `client-godot/src/ui/draft_window.gd:6` | 标题 |
| 草稿窗口放弃确认 | 同上 | `关闭后，本窗口未保存的内容将被丢弃。` | `client-godot/src/ui/draft_window.gd:7` | 正文 |
| 草稿窗口放弃确认 | 确认按钮 | `放弃修改` | `client-godot/src/ui/draft_window.gd:8` | |
| 草稿窗口放弃确认 | 取消按钮 | `取消` | `client-godot/src/ui/draft_window.gd:9` | |
| Toast | 任意 | `{text}` | `client-godot/src/ui/toast_overlay.gd:69` | 组件无固定文案，由调用方传入 |
| 下拉触发按钮 | 有选中项且显示标签 | `{label}  ▾` | `client-godot/src/ui/unified_dropdown.gd:72` | 两个空格 + `▾` |
| 下拉菜单行 | 当前选中 | `✓  {label}` | `client-godot/src/ui/unified_dropdown.gd:168` | 勾号后两个空格 |
| 下拉菜单行 | 未选中 | `    {label}` | `client-godot/src/ui/unified_dropdown.gd:168` | 四个空格前缀 |

## 7. 预览样板（非正式客户端）

以下文案只在 `-- --preview` 离线样板中出现，不连接服务器，不属于正式功能文案。列出是为了避免误改或误删。

| 场景 | 触发/状态 | 当前文案 | 位置 | 备注 |
|---|---|---|---|---|
| 角色名 | 样板角色区 | `洛天依` | `client-godot/scenes/preview/chat_preview.tscn:87` | |
| 角色签名 | 样板角色区 | `把平凡的日子，慢慢说给我听。` | `client-godot/scenes/preview/chat_preview.tscn:92` | |
| 表情菜单 | 样板左上 | `微笑脸` / `温柔脸` / `喜欢脸` / `卖萌` / `生气脸` / `难过脸` / `唱歌` | `client-godot/scenes/preview/chat_preview.tscn:98-110` | 下拉选项 |
| 聊天标题 | 样板 | `和天依聊聊` | `client-godot/scenes/preview/chat_preview.tscn:130` | |
| 场景菜单 | 样板右上 | `日常聊天` / `空白会话` / `网络断开` / `加载失败` / `正在思考` | `client-godot/scenes/preview/chat_preview.tscn:136-144` | 下拉选项 |
| 离线标识 | 样板 | `离线样板 · 未连接服务器` | `client-godot/scenes/preview/chat_preview.tscn:150` | |
| 回到最新 | 样板 | `回到最新 ↓` | `client-godot/scenes/preview/chat_preview.tscn:174` | |
| 图片按钮 | 样板 | `＋ 图片` | `client-godot/scenes/preview/chat_preview.tscn:186` | |
| 口型按钮 | 样板 | `▷ 模拟口型 / 停止` | `client-godot/scenes/preview/chat_preview.tscn:190` | |
| 输入框 | 样板 | `想说些什么？` | `client-godot/scenes/preview/chat_preview.tscn:195` | placeholder |
| 快捷键提示 | 样板 | `Enter 发送 · Shift + Enter 换行` | `client-godot/scenes/preview/chat_preview.tscn:207` | |
| 发送按钮 | 样板 | `发送  ↑` | `client-godot/scenes/preview/chat_preview.tscn:213` | |
| 图片过滤器 | 样板 | `*.png, *.jpg, *.jpeg, *.webp ; 图片` | `client-godot/scenes/preview/chat_preview.tscn:219` | |
| 场景状态 | 日常聊天 | `所有发送状态均为模拟。可以继续输入。` | `client-godot/src/preview/chat_preview.gd:117` | |
| 场景状态 | 空白会话 | `还没有消息。写下第一句话吧。` | `client-godot/src/preview/chat_preview.gd:117` | |
| 场景状态 | 网络断开 | `网络已断开 · 模拟状态，草稿会保留` | `client-godot/src/preview/chat_preview.gd:117` | |
| 场景状态 | 加载失败 | `历史加载失败 · 模拟状态，草稿会保留` | `client-godot/src/preview/chat_preview.gd:117` | |
| 场景状态 | 正在思考 | `天依正在想一想… · 模拟状态` | `client-godot/src/preview/chat_preview.gd:117` | |
| 空态 | 网络断开 | `连接暂时中断` | `client-godot/src/preview/chat_preview.gd:106` | |
| 空态 | 加载失败 | `暂时无法加载消息` | `client-godot/src/preview/chat_preview.gd:106` | |
| 图片读取失败 | 样板选图失败 | `无法读取这张图片，请重新选择。` | `client-godot/src/preview/chat_preview.gd:146` | |
| 模拟口型 | 播放/停止 | `模拟播放中 · 仅演示口型，无声音` / `模拟播放已停止` | `client-godot/src/preview/chat_preview.gd:164` | |
| 比例保存失败 | 拖动分栏失败 | `分区比例无法保存。` | `client-godot/src/preview/chat_preview.gd:60` | |
| 示例消息 | 样板 | `今天  14:32 · 以下为界面演示内容` | `client-godot/src/preview/demo_session.gd:14` | 系统消息；两个空格 |
| 示例消息 | 样板 | `你回来啦。今天过得怎么样？` | `client-godot/src/preview/demo_session.gd:15` | |
| 示例消息 | 样板 | `终于忙完了，想在这里休息一会儿。` | `client-godot/src/preview/demo_session.gd:16` | |
| 示例消息 | 样板 | `那就慢慢来吧，不用急着说些什么。\n我在这里，陪你把今天的心情一点点放下来。` | `client-godot/src/preview/demo_session.gd:17` | |
| 示例消息 | 样板 | `给你看看今天的小角落。` | `client-godot/src/preview/demo_session.gd:18` | |
| 示例消息 | 样板 | `这条用来看看发送中的样子。` | `client-godot/src/preview/demo_session.gd:19` | |
| 示例消息 | 样板 | `这条是发送失败的示例，文字仍然保留。` | `client-godot/src/preview/demo_session.gd:20` | |
| 示例图片 | 样板 | `[图片]` | `client-godot/src/preview/chat_preview.gd:155` | 仅用于模拟发送图片的占位文本 |

## 8. 格式化模板索引

这些模板已分散在上表，集中列出便于统一检查数字、单位和标点。

| 类型 | 模板 | 位置 | 说明 |
|---|---|---|---|
| 标题 | `%s %s` | `client-godot/src/storage/release_info.gd:8` | 产品名 + 版本 |
| 计数 | `动态 · %s 条未读` | `client-godot/src/application.gd:149` | 导航 tooltip |
| 计数 | `动态 · %s` | `client-godot/src/ui/dynamics_window.gd:167` | 顶部标签 |
| 计数 | `后台同步历史 · 已加载 %s 条` | `client-godot/src/ui/chat_view.gd:370` | |
| 计数 | `已保存 %d 项；%d 项未保存，修改仍保留在本次会话。` | `client-godot/src/ui/settings_window.gd:179` | |
| 计数 | `已识别客户端：语音 %d 条，图片 %d 张。` | `client-godot/src/ui/audio_settings_page.gd:110` | |
| 计数 | `已处理 %d 条（语音 %d、图片 %d）：导入 %d 条，跳过 %d 条，失败 %d 条。` | `client-godot/src/ui/audio_settings_page.gd:272` | |
| 进度 | `正在导入 %d / %d（语音 %d / %d，图片 %d / %d）…` | `client-godot/src/ui/audio_settings_page.gd:230` | |
| 时间 | `%s分钟前` / `%s小时前` / `%s天前` | `client-godot/src/ui/dynamic_detail.gd:262-264` | 数字与单位之间无空格 |
| 时间 | `%.1f 秒` / `%.1f/%.1f 秒` | `client-godot/src/ui/message_audio.gd:39` | 秒前有空格 |
| 容量 | `%.2f%%` / `%.2f %s` / `%s bytes` | `client-godot/src/ui/audio_settings_page.gd:306`、`:322`、`:326` | |
| 缩放 | `%s%%` | `client-godot/src/ui/image_window.gd:81` | 例：`100%` |
| 评论 | `回复 %s：` | `client-godot/src/ui/dynamic_detail.gd:181` | 全角冒号 |
| 角色 | `%s · 未读动态` | `client-godot/src/avatar/avatar_panel.gd:24` | 作者名 + 空格 + `·` + 空格 |
| 模型 | `调用要求：%s%s%s` | `client-godot/src/ui/model_purpose_card.gd:21` | 模型类型 + JSON 后缀 + thinking 后缀 |
| 账号 | `移除“%s”的本机账号记录和已记住的登录状态？不会删除服务器账号或聊天、语音缓存。` | `client-godot/src/ui/account_view.gd:216` | |
| 日志 | `共 %s 条记录（%s）；筛选只影响显示，导出包含整次启动。` | `client-godot/src/ui/log_window.gd:138` | |
| 日志 | `客户端日志 · %s %s` | `client-godot/src/ui/log_window.gd:31` | |

## 9. 非固定文案与服务端内容

以下内容会显示在界面上，但不是客户端固定文案，改写本文不会影响它们：

- LLM 回复正文、流式回复、角色名/签名以外的对话内容。
- 动态正文、动态作者名、动态发布时间、评论正文、评论作者名、评论时间原串。
- 用户名、本机保存的服务器地址、客户端路径、模型服务商、Base URL、模型名、API Key（输入框内容）。
- 模型用途名称与说明：来自服务端 `/llm/client-model-types`，客户端只提供 `模型用途` 兜底。
- 动态类型标签、错误码、日志类别/模块/归属 ID：客户端有一层映射，但实际值受服务端/日志实现影响。
- 日志行的事件说明（`客户端启动`、`消息投递状态` 等）来自 `client-godot/src/storage/log_schema.gd:65-126`，属于诊断文案；本文只登记了筛选标签和兜底文案，未逐条展开事件说明。
- 系统文件选择器的窗口装饰、默认按钮和路径栏由 Windows 绘制。
- 日志正文、堆栈、JSON 指标、事件名和错误码属于诊断内容，不作为产品文案维护。

## 10. 覆盖自检与已知不可见项

已逐文件检查以下范围（仅统计会渲染到 UI 的固定文案，含 tooltip、placeholder、确认框和文件对话框传入值）：

| 文件 | 结果 |
|---|---|
| `client-godot/src/application.gd` | 已覆盖：窗口标题、导航 tooltip、安全阻断、账号存储警告 |
| `client-godot/src/application/window_coordinator.gd` | 已覆盖：退出/登出确认标题、正文、草稿项 |
| `client-godot/scenes/main.tscn` | 已覆盖：导航、退出确认按钮、静态安全文案、存储警告 |
| `client-godot/src/ui/account_view.gd` + `scenes/ui/account_view.tscn` | 已覆盖：登录/注册/重置、服务器、状态码、账号列表、移除确认 |
| `client-godot/scenes/ui/login_account_row.tscn` | 已覆盖：移除按钮与 tooltip |
| `client-godot/src/ui/chat_view.gd` + `scenes/ui/chat_view.tscn` | 已覆盖：状态、历史、输入区、图片、错误码、消息状态 |
| `client-godot/src/ui/message_bubble.gd` + `.tscn` | 已覆盖：图片状态、加载失败 |
| `client-godot/src/ui/message_audio.gd` + `.tscn` | 已覆盖：重放/暂停/继续、停止、时长、失败 |
| `client-godot/src/ui/chat_time.gd` | 已覆盖：时间显示格式 |
| `client-godot/src/avatar/avatar_panel.gd` + `scenes/avatar/avatar_panel.tscn` | 已覆盖：未读动态卡片、重置位置、资源缺失 |
| `client-godot/src/ui/dynamics_window.gd` + `.tscn` | 已覆盖：列表、占位、未读、刷新、错误 |
| `client-godot/src/ui/dynamics_post_row.gd` + `.tscn` | 已覆盖：作者、类型、元信息、摘要 |
| `client-godot/src/ui/dynamic_detail.gd` + `.tscn` | 已覆盖：正文、评论、回复、相对时间、错误 |
| `client-godot/src/ui/dynamic_comment_row.gd` + `.tscn` | 已覆盖：作者、正文、时间 tooltip、回复 |
| `client-godot/src/ui/publish_overlay.gd` + `.tscn` | 已覆盖：标题、输入、按钮、错误、放弃确认 |
| `client-godot/src/ui/settings_window.gd` + `.tscn` | 已覆盖：页签、底部按钮、保存提示、未保存确认 |
| `client-godot/src/ui/profile_page.gd` + `.tscn` | 已覆盖：账号、说明、按钮、成功/失败、文件对话框 |
| `client-godot/src/ui/preferences_page.gd` + `.tscn` | 已覆盖：标签、placeholder、选项、默认值、提示 |
| `client-godot/src/ui/model_page.gd` + `.tscn` | 已覆盖：标题、说明、状态、弹窗、错误 |
| `client-godot/src/ui/model_purpose_card.gd` + `.tscn` | 已覆盖：用途名/说明、字段、开关、调用要求、状态 |
| `client-godot/src/ui/style_page.gd` + `.tscn` | 已覆盖：标签、placeholder、选项、保存失败 |
| `client-godot/src/ui/audio_settings_page.gd` + `.tscn` | 已覆盖：说明、导入、清理、容量、确认框、进度、错误 |
| `client-godot/src/ui/log_window.gd` + `.tscn` | 已覆盖：标题、筛选、按钮、状态、导出、错误 |
| `client-godot/src/ui/error_dialog.gd` + `.tscn` | 已覆盖：默认标题、关闭、确认 |
| `client-godot/src/ui/decision_dialog.gd` + `.tscn` | 已覆盖：默认按钮、关闭 tooltip、保存并关闭 |
| `client-godot/src/ui/draft_window.gd` | 已覆盖：草稿放弃确认 |
| `client-godot/src/ui/unified_dropdown.gd` | 已覆盖：触发按钮后缀、菜单勾选/缩进 |
| `client-godot/src/ui/toast_overlay.gd` | 无固定文案 |
| `client-godot/src/storage/log_schema.gd` | 已覆盖：类别/归属标签；模块 ID 原样显示 |
| `client-godot/scenes/preview/chat_preview.tscn` + `src/preview/*` | 已覆盖：离线样板文案，单独列在第 7 节 |

以下 UI 脚本只含注释或数据绑定，没有固定用户文案：`composer_input.gd`、`composer_resize_handle.gd`、`dropdown_item.gd`、`image_thumb_button.gd`、`message_waveform.gd`、`popup_trigger.gd`、`virtual_message_list.gd`、`window_chrome.gd`、`frost_surface.gd`。

已知当前不可见或需要复核的项：

- `client-godot/scenes/ui/image_window.tscn:42` 的 `图片暂时无法读取，请重试。`：`image_window.gd:63` 始终把 `%ImageError.visible` 设为 `false`，实际失败走 `:67` 的弹窗。
- `client-godot/src/ui/publish_overlay.gd:33` 的 `%PublishStatus`、`client-godot/src/ui/dynamic_detail.gd:216` 的 `%Status`、`client-godot/src/ui/image_window.gd:25` 的 `%Feedback`：当前只写入空字符串。
- `client-godot/src/ui/message_bubble.gd:159` 的 `%Caption`：自己的消息每次都会清空，不会显示「发送失败」；失败提示改由聊天页弹窗统一给出。
- `client-godot/scenes/ui/message_audio.tscn:36` 的 `语音未能保存`：`message_audio.gd:30` 始终隐藏。
- `client-godot/scenes/main.tscn:215` 的 `凭据保护组件缺失，请重新解压完整程序。`：运行时被 `账号与聊天功能暂不可用` 覆盖，通常不可见。
- `client-godot/src/ui/log_window.gd:100` + `:104` 的 `本次启动（未能保存） · 本次启动`：按拼接逻辑会重复「本次启动」，建议复核。
- `client-godot/scenes/ui/audio_settings_page.tscn:166` 的 tooltip 挂在普通 `Label` 上；若该控件保持默认 `mouse_filter=IGNORE`，tooltip 可能无法触发。
- `client-godot/src/ui/profile_page.gd:43` 的用户名可能为空，此时显示 `—`。
- `client-godot/src/session/preferences_controller.gd:89` 的 `朋友`/`活泼可爱` 只在服务端加载成功且字段为空时进入输入框。

## 11. 其他子项目入口（未逐条展开）

本文聚焦当前在研的 `client-godot`。仓库中其他面向用户的界面仍存在，若需要统一改写，可另出对应清单：

| 子项目 | 界面入口 | 说明 |
|---|---|---|
| `app/` | `app/app/index.tsx`、`login.tsx`、`dynamics.tsx`、`preferences.tsx`、`llm_settings.tsx` | Expo / React Native 移动客户端，文案主要在页面组件内 |
| `client/` | `client/src/gui/` | PySide6 桌面客户端，文案主要在窗口、对话框和气泡组件内 |
| `cli-client/` | `cli-client/cli_client/cli/` | 命令行客户端，输出文案在命令、动作和输出模块内 |
| 管理控制台 | `server/res/admin_ui/src/` | 服务端附带的 Web 控制台，文案在前端源码内 |
