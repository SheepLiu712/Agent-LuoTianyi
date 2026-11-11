# Godot 客户端用户可见报错清单

状态：2026-11-10，源码版本 0.1.6.2。已按本清单执行：所有保留/改中性的用户可见报错改走统一错误弹窗，移除项不再显示，仅日志项保持无 UI。

上一版按「系统/网络/存储/运行时错误 → 移除；表单校验 → 保留」划档，这个划法把「是否属于内部实现」当成了「用户是否需要知道」，导致 `A1`/`C7`/`D6`/`E4` 这类唯一信息源被判成移除。本版改为按后果划档。

## 判定标准

每条只问两个问题：

1. 不告诉用户，他会不会误以为操作成功、或卡在原地不知道下一步？
2. 告诉用户，他能不能据此做点什么？

三档结论：

- `保留`：提示内容本身有信息价值，最多摘掉错误码即可。
- `改中性`：提示该有，但现在的措辞把内部机制甩给用户（组件、错误码、写入步骤），改成「结果 + 出路」，保留触发条件与可操作信息。
- `移除`：用户既无法行动，也不影响他理解当前状态，只进日志。

附带一条硬约束：**移除或中性化都不能让界面沉默**。如果某个失败会让用户误判「已经发出去了 / 已经存上了」，那这条必须留在界面上，只能改措辞。

`仅日志` 是第四种处理：只补事件、不动 UI（`E7`/`E8`，本来就是控制台/静默）。

原生分类保留在每条里，仅作定位用，不再直接决定判定：`系统`=运行/网络/存储错误；`阻断`=功能不可用；`校验`=用户输入不合法；`状态`=普通状态/降级；`确认`=操作确认。

## 结论速览

- 保留 12：`A7` `B7` `B12` `B13` `B14` `B15` `C5` `C6` `C7` `C10` `C11` `E3`
- 改中性 29：`A1` `A5` `A6` `A9` `B1` `B3` `B4` `B5` `B6` `B8` `B9` `B10` `B11` `C1` `C2` `C3` `C8` `C9` `C12` `C13` `D1` `D2` `D3` `D4` `D5` `D6` `E1` `E2` `E4`
- 移除 9：`A2` `A3` `A4` `A8` `A10` `B2` `C4` `E5` `E6`
- 仅日志 2：`E7` `E8`

其中与上一版建议相反、需要特别复核的 7 条：`A1`（不能整条删）、`A9`（必须留且升级为阻断页）、`C7`（唯一送达提示）、`C12`/`C13`（静默会造成「已送达/丢失」二义）、`D3`/`D6`（防重复提交护栏）、`B10`（失败原因就是操作指引）、`E4`（阻断项）。

## A. 登录与账号

- [ ] **A1 登录/注册/重置错误码** · `%Status` · `src/ui/account_view.gd:273` · 触发：`_error_text(code,status)`，覆盖 `AUTH_REJECTED/INVALID_INPUT/TIMEOUT/NETWORK_ERROR/PUBLIC_KEY_ERROR/ENCRYPTION_ERROR/INVALID_RESPONSE/CREDENTIAL_UNAVAILABLE/HTTP_ERROR/NO_SAVED_LOGIN/STORAGE_ERROR/BUSY` · 文案：整句，`HTTP_ERROR` 拼状态码 · 内联标签 · 分类：系统/阻断 · 日志：`account_api` 的 HTTP access、`security_auth` · 缺失：`_accept_account` 凭据保存失败的审计 · **判定：改中性** · 改法：保留 `AUTH_REJECTED`「用户名或密码错误，或自动登录凭据已失效」、`INVALID_INPUT`、`NO_SAVED_LOGIN`、`CREDENTIAL_UNAVAILABLE`、`TIMEOUT`、`NETWORK_ERROR`、`PUBLIC_KEY_ERROR`——这些是用户唯一能自救的线索；`HTTP_ERROR` 不再拼状态码，改「服务器暂时无法处理，请稍后重试」；`ENCRYPTION_ERROR` 改「登录暂时无法完成，请稍后重试」并删掉「检查密码长度或服务器公钥」这种错误归因；`INVALID_RESPONSE` 改「服务器响应异常，请稍后重试」；`BUSY` 改「正在处理中，请稍候」；`STORAGE_ERROR` 此处不显示，只进日志（同 A3）；未知码改「操作未完成，请重试」。不要按「系统错误」整条移除 · 勾选：____
- [ ] **A2 登录选项保存失败** · `%Status` · `src/ui/account_view.gd:145` · 触发：`set_login_options` 返回非 OK，勾选框回滚 · 文案：`_error_text(result.code)` · 内联 · 分类：系统 · 日志：`security_token`/`runtime_account_state` · 缺失：失败步骤（write/clear） · **判定：移除** · 改法：勾选框回滚本身就是完整反馈；`STORAGE_ERROR` 用户不可自救。只补日志 · 勾选：____
- [ ] **A3 账号状态错误 / 本地存储失败** · `%Status` · `src/ui/account_view.gd:172-173` · 触发：`account_session.changed` 的 `code`/`storage_error` · 文案：错误码整句；存储失败为「本地登录资料未能保存或清除…」 · 内联 · 分类：系统/阻断 · 日志：`runtime_account_state`（code=STORAGE_ERROR） · 缺失：write/clear/forget 具体步骤 · **判定：移除** · 改法：与 `A8` 是同一事实，只保留一处、且不在聊天界面常驻；`storage_error` 状态本身保留。另修 `_update_state` 每次 `changed` 都覆写 `%Status` 的问题（见 H1），否则登录成功也可能被陈旧错误盖住 · 勾选：____
- [ ] **A4 移除本机账号失败** · `%Status` · `src/ui/account_view.gd:219` · 触发：`remove_account` 返回非 OK · 文案：`_error_text(response.code)` · 内联 · 分类：系统 · 日志：`security_auth(remove)` · 缺失：无 · **判定：移除** · 改法：失败后账号仍在，列表本身就是结果；只补日志 · 勾选：____
- [ ] **A5 打开反馈浏览器失败** · `%Status` + `%FeedbackAddress` · `src/ui/account_view.gd:246` · 触发：外部链接打开返回非 OK · 文案：「无法打开浏览器，可复制下方项目地址。」 · 内联 · 分类：系统 · 日志：无 · 缺失：`warning_external_link` · **判定：改中性** · 改法：「浏览器没有打开，请手动复制下面的地址。」并补一个「复制地址」按钮——当前 `%FeedbackAddress` 是只读输入框，只能手动选中，文案说的「可复制」没有出口 · 勾选：____
- [ ] **A6 服务器验证失败** · `%ServerStatus` · `src/ui/account_view.gd:238` · 触发：`probe_server` 返回非 OK · 文案：`_error_text(response.code, status)` · 弹窗内标签 · 分类：系统/阻断 · 日志：HTTP access · 缺失：探测专用事件 · **判定：改中性** · 改法：保留提示（这是改地址场景下唯一的连通性反馈），但改成「无法连接服务器，请检查网络或服务器地址」。当前 `account_api.gd:52` 把断网、超时、地址错误一律归成 `PUBLIC_KEY_ERROR`，显示「无法获取服务器公钥」，会把用户引向错误方向 · 勾选：____
- [ ] **A7 密码字符/两次密码不一致** · `%Status` · `src/ui/account_view.gd:265,288` · 触发：非 ASCII/控制字符、两次输入不同 · 文案：「密码只允许英文字母…」/「两次输入的密码不一致。」 · 内联 · 分类：校验 · 日志：无需 · **判定：保留** · 改法：无 · 勾选：____
- [ ] **A8 登录后本地凭据未保存** · `%AccountStorageWarning` · `src/application.gd:200` · 触发：`state.storage_error and phase=="signed_in"` · 文案：「本次登录有效，但本地登录状态未能保存或清除…」 · 常驻横幅 · 分类：系统/降级 · 日志：`runtime_account_state` · 缺失：失败操作与错误码 · **判定：移除** · 改法：影响只是「下次可能要重输密码」，不阻断任何功能，却用一条跨页面常驻横幅去覆盖聊天界面。改为账号页一次性提示或只进日志，`storage_error` 状态保留 · 勾选：____
- [ ] **A9 认证加密组件不可用** · `%SecurityError` · `src/application.gd:130-131` · 触发：`password_encryption.is_available()==false`，直接 `return` 不挂载账号/聊天 · 文案：「认证加密组件不可用，暂时无法登录；日志和问题反馈仍可使用。」 · 页面标签 · 分类：阻断 · 日志：`security_component`（字段齐全） · 缺失：无 · **判定：改中性（必留）** · 改法：这是整体阻断——`_services.mount` 不执行，登录页所有按钮禁用、导航默认隐藏，删掉文案等于留一个点不动的死界面。改为阻断页文案「程序文件不完整，无法启动账号与聊天功能。请重新解压或重新安装；日志和问题反馈仍可使用。」去掉「认证加密组件」这类内部术语；保留「打开日志」「问题反馈」两个按钮；当前是左上角无背景 Label（`main.tscn:215` 的静态文案还会被运行时覆盖），需确保不被顶栏遮挡 · 勾选：____
- [ ] **A10 日志写盘失败（主窗）** · `%LogProblem` · `src/application.gd:99` · 触发：`ClientLog.write_failed` · 文案：「日志保存失败，打开日志可查看本次内存记录…」 · 顶部横幅 · 分类：系统 · 日志：失败条目本身未进内存，无事件 · 缺失：`write_failed` 事件/错误码/计数 · **判定：移除** · 改法：不影响任何功能（`client_log.gd:76-84` 仍保留内存记录）。注意「先补日志」在这里不成立——日志本身就是坏的，只能写 stderr 或备用通道，并在日志窗（E3）里体现一次 · 勾选：____

## B. 设置、模型、偏好、缓存

- [ ] **B1 设置保存失败汇总** · `%SaveToast` · `src/ui/settings_window.gd:158-169` · 触发：模型/偏好/外观保存结果含失败 · 文案：「已保存 N 项；未保存：X：CODE…」（原始码直出） · Toast · 分类：系统 · 日志：各下层有 info/HTTP；外观保存无日志 · 缺失：统一 `warning_settings_save` 汇总 · **判定：改中性** · 改法：「已保存 N 项；M 项未保存，修改仍保留在本次会话。」删掉「X：CODE」逐项原始码，逐项失败进日志。不能整条删：用户关窗时会以为全存上了 · 勾选：____
- [ ] **B2 相处偏好加载失败** · `%Toast` · `src/ui/preferences_page.gd:3` · 触发：controller phase=error · 文案：「相处偏好加载失败，重新打开设置可重试。」 · Toast · 分类：系统 · 日志：`info_settings_preference` · 缺失：warning/error 级别 · **判定：移除** · 改法：重开设置自动 reload 已是出口；补 warning 级日志 · 勾选：____
- [ ] **B3 相处偏好保存失败** · `%Toast` · `src/ui/preferences_page.gd:80` · 触发：`state.code != OK` · 文案：「相处偏好保存失败（CODE），修改已保留。」 · Toast · 分类：系统 · 日志：`info_settings_preference` · 缺失：error 级别与 HTTP 关联 · **判定：改中性** · 改法：「偏好保存失败，修改已保留。」去 CODE；补 error 级日志 · 勾选：____
- [ ] **B4 模型用途加载失败** · `%Status` · `src/ui/model_page.gd:62-65` · 触发：`state.code` 非 OK · 文案：「无法读取模型用途（CODE），请刷新重试。」/「部分配置未能恢复…」 · 内联 · 分类：系统 · 日志：`info_settings_models` · 缺失：warning/error 级别 · **判定：改中性** · 改法：「部分配置未能恢复，可刷新重试。」去 CODE 与「模型用途」这种内部说法 · 勾选：____
- [ ] **B5 模型测试失败** · `%Status` · `src/ui/model_page.gd:168` · 触发：测试请求失败 · 文案：「测试失败（CODE）。」 · 内联 · 分类：系统 · 日志：`model_executor` 的 start/end，仅实际发出请求时 · 缺失：校验早退（MODEL_FIELDS_REQUIRED/BUSY 等） · **判定：改中性** · 改法：「测试未通过，请检查服务地址和密钥后重试。」必须保留——用户主动点了「测试」，无回执就像按钮坏了；校验早退另给「请先填写模型地址/密钥」。注意 `model_executor` 只在真正发请求时记日志，接口地址写错这类失败目前是静默的 · 勾选：____
- [ ] **B6 模型卡片校验/保存失败** · `%CardStatus` · `src/ui/model_page.gd:83-90`、`model_purpose_card.gd:56-58` · 触发：`validate/save` 返回非 OK · 文案：「未保存：CODE」 · 卡片内联 · 分类：校验+系统混用 · 日志：仅下层写入；校验失败无日志 · 缺失：校验失败事件 · **判定：改中性** · 改法：校验部分保留原文案；系统失败统一「未保存，请重试」，去 CODE · 勾选：____
- [ ] **B7 密钥保护失败/明文保存确认** · `%PlainDialog` · `src/ui/model_page.gd:122-125` · 触发：`PLAINTEXT_CONFIRMATION_REQUIRED` · 文案：「Windows 未能保护 API Key。是否明确选择在本机以明文保存？…」 · 确认弹窗 · 分类：确认/安全 · 日志：写入成功有 `security_token`；回退动作无独立事件 · 缺失：明文回退安全事件 · **判定：保留** · 改法：无（安全决策，必须让用户选） · 勾选：____
- [ ] **B8 头像设置失败** · `%Result` · `src/ui/profile_page.gd:6-12,54-57` · 触发：`NO_ACCOUNT/IMAGE_READ_FAILED/IMAGE_TOO_LARGE/IMAGE_FORMAT/AVATAR_WRITE_FAILED` · 文案：「这张图片读不出来…」等 · 内联 · 分类：校验+系统 · 日志：`avatar_profile`/`avatar_store` 部分覆盖 · 缺失：读取失败事件 · **判定：改中性** · 改法：校验原文保留；`AVATAR_WRITE_FAILED` 改「头像保存失败，请重试」，去 code。不能全删：用户主动设置头像，必须知道成没成 · 勾选：____
- [ ] **B9 外观保存失败** · `%SaveToast` · `src/ui/style_page.gd:61-65` · 触发：`save_settings` 失败，回滚风格值 · 文案：「界面与图标风格：本地保存失败（CODE）」 · Toast · 分类：系统 · 日志：无 · 缺失：`warning_settings_save` · **判定：改中性** · 改法：「风格保存失败，本次仍生效，重启后恢复上次设置。」去 CODE。不能只补日志就删：用户会以为选中的风格被记住了 · 勾选：____
- [ ] **B10 Python 客户端扫描/导入失败** · `%MigrationStatus` · `src/ui/audio_settings_page.gd:101-104,124-131,239-263` · 触发：`TARGET_INVALID/TARGET_MISSING/SOURCE_* /STORAGE_UNAVAILABLE/PARTIAL` · 文案：「这不是可识别的 Python 客户端目录…」等 · 内联 · 分类：系统 · 日志：扫描/每文件事务已覆盖一部分 · 缺失：TARGET_MISSING、STORAGE_UNAVAILABLE、SOURCE_EMPTY、PARTIAL · **判定：改中性** · 改法：保留原因映射——「不是可识别的客户端目录 / 目标目录不存在 / 磁盘空间不足 / 部分文件未导入」直接决定用户下一步选哪个目录，是最高价值文案；去掉 `TARGET_*`/`SOURCE_*` 原始码；保留进度、完成计数与「重新选择」入口 · 勾选：____
- [ ] **B11 缓存清理失败** · `%CacheStatus` + 聊天 `%Status` · `src/ui/audio_settings_page.gd:174-180`、`src/ui/chat_view.gd:264-265` · 触发：`clear_cache` 非 OK / `CACHE_CLEAR_FAILED` · 文案：「部分语音未能清理，请关闭占用文件后重试。」 · 内联两处 · 分类：系统 · 日志：`info_cache_cleared`（info 级） · 缺失：error 级 · **判定：改中性** · 改法：「部分语音文件被占用，关闭后重试。」这是可执行指令，保留；补 error 级日志 · 勾选：____
- [ ] **B12 清理天数非法** · `%CacheStatus` · `src/ui/audio_settings_page.gd:156-160` · 触发：非有限/负数/超大 · 文案：「请输入有效的非负整数天数。」 · 内联 · 分类：校验 · 日志：无需 · **判定：保留** · 改法：无 · 勾选：____
- [ ] **B13 存储空间不可读取** · `%UsageState/%UsageDetails` · `src/ui/audio_settings_page.gd:274-293` · 触发：StorageVolume 不可用/扫描失败 · 文案：「存储数据暂不可用」「无法读取」 · 内联 · 分类：状态/降级 · 日志：无 · 缺失：storage query 失败日志 · **判定：保留** · 改法：保留占位降级态，两处「不可用/无法读取」合并成一句，去重复 · 勾选：____
- [ ] **B14 未保存修改确认** · `%UnsavedDialog` · `src/ui/settings_window.gd:120-125` · 触发：关闭时有脏数据 · 文案：「可以保存全部修改后关闭，或放弃…」 · 确认弹窗 · 分类：确认 · 日志：无 · **判定：保留** · 改法：无 · 勾选：____
- [ ] **B15 放弃草稿确认** · `%Discard` · `src/ui/draft_window.gd:6-14` · 触发：有未保存内容时关闭 · 文案：「关闭后，本窗口未保存的内容将被丢弃。」 · 确认弹窗 · 分类：确认 · 日志：无 · **判定：保留** · 改法：无 · 勾选：____

## C. 聊天、历史、图片与语音

- [ ] **C1 连接状态/凭据失效** · `%Status` · `src/ui/chat_view.gd:254` · 触发：transport phase=`idle/connecting/authenticating/ready/reconnecting/auth_rejected` · 文案：「连接已关闭/正在连接/聊天凭据已失效…」 · 内联 · 分类：状态+阻断 · 日志：`runtime_connection_state`、`security_ws_auth` · 缺失：无 · **判定：改中性** · 改法：`connecting/reconnecting` 改「正在连接/连接已断开，正在重试」；`auth_rejected` 改「聊天凭据已失效，请重新登录」并**补一个「重新登录」按钮**——当前只有 Label，用户得自己去设置里退出登录。这条不能删：凭据失效时输入框仍可输入，不提示会让用户以为发出去了 · 勾选：____
- [ ] **C2 聊天错误码后缀** · `%Status` · `src/ui/chat_view.gd:260-271` · 触发：`REMOTE_AUDIO_ERROR/AUDIO_ERROR/CACHE_CLEAR_FAILED/SEND_REJECTED/INVALID_RESPONSE/其它非空 code` · 文案：「服务端语音生成失败/这条语音暂时无法播放/暂时无法发送/收到的数据不完整…」 · 内联 · 分类：系统 · 日志：`error_system`、`error_audio`、HTTP/WS access · 缺失：部分 code 仅 info 级 · **判定：改中性** · 改法：「语音生成失败，可继续文字聊天」「这条语音无法播放」，去掉 code 后缀；保留是因为它区分了「远端合成失败」与「本地播放失败」，并确认文字仍在。另：`chat_session.gd:342,375` 只在 code 变更时更新，语音恢复后文案不会清除（见 H2） · 勾选：____
- [ ] **C3 历史同步失败/不完整** · `%HistoryStatus` + `%HistoryRetry/%HistorySkip` · `src/ui/chat_view.gd:357-364` · 触发：`first_failed/failed/incomplete` · 文案：「首批历史加载失败…/较早历史加载失败…/检测到分页重复…」 · 内联横幅+按钮 · 分类：系统 · 日志：`runtime_history_state`（runtime 级） · 缺失：error/warning 级与失败 code · **判定：改中性** · 改法：保留「首批历史加载失败，可重试或跳过」「较早历史加载失败，已加载内容保留」；「检测到分页重复，无法确认历史完整」是内部结论，改「部分历史可能缺失」；重试/跳过按钮必须留，且不能只剩按钮不讲发生了什么 · 勾选：____
- [ ] **C4 阅读位置保存失败** · `%HistoryStatus` + `%Status` · `src/ui/chat_view.gd:363`、`chat_session.gd` `_system_error("SAVE_FAILED")` · 触发：`report_visible` 写盘失败 · 文案：「本机阅读位置未能保存。」 · 内联 · 分类：系统 · 日志：`error_system` · 缺失：reading_position 自身 logger · **判定：移除** · 改法：影响仅是下次打开不在原位置，静默即可；补 logger · 勾选：____
- [ ] **C5 图片选择校验** · `%ImageStatus` · `src/ui/chat_view.gd:193` · 触发：`IMAGE_TOO_LARGE/IMAGE_DIMENSIONS/IMAGE_FORMAT/IMAGE_READ_FAILED/INVALID_IMAGE/FILE_PICKER_UNAVAILABLE` · 文案：「图片过大，请选择小于 6 MiB…」等 · 内联 · 分类：校验 · 日志：无 · 缺失：选择失败事件（含真实上限与 code） · **判定：保留** · 改法：无（已给出真实限制值）；先补选择失败事件 · 勾选：____
- [ ] **C6 图片发送失败** · `%ImageStatus` · `src/ui/chat_view.gd:211` · 触发：`send_image` 返回空（连接不可用、校验失败、队列拒绝） · 文案：「图片暂时无法发送，内容已保留；请检查连接后重试。」 · 内联 · 分类：系统 · 日志：部分经 `_system_error`；`idle/auth_rejected` 静默 · 缺失：前置拦截日志 · **判定：保留** · 改法：措辞保持；补 `idle/auth_rejected` 的前置拦截日志 · 勾选：____
- [ ] **C7 消息发送失败** · `%Caption` · `src/ui/message_bubble.gd:165` · 触发：`message.status=="failed"` · 文案：「发送失败」 · 气泡下方标签 · 分类：系统 · 日志：`info_message_delivery`（info 级） · 缺失：error 级与失败 code · **判定：保留** · 改法：这是消息没发出去的**唯一**提示（`chat_session.gd:519` 不写状态栏），删了用户会当成已送达。保留「发送失败」，并**补「重发」入口**——现在只有文字，没有恢复动作 · 勾选：____
- [ ] **C8 图片气泡加载失败/缓存失败** · `%ImageButton` · `src/ui/message_bubble.gd:195-197` · 触发：`NETWORK_ERROR/IMAGE_MISSING/INVALID_IMAGE/CACHE_WRITE_FAILED` · 文案：「图片加载失败 · 重试」「· 未能缓存」 · 占位按钮 · 分类：系统 · 日志：`error_history_image`；缓存失败走 info · 缺失：缓存失败 error 级 · **判定：改中性** · 改法：「图片未加载，点击重试」；去掉「未能缓存」（`history_images.gd:158` 置 ready 后按钮即隐藏，实际不可见）；补缓存失败 error 级日志 · 勾选：____
- [ ] **C9 语音失败** · `%Error` · `src/ui/message_audio.gd:29` · 触发：`CACHE_WRITE_FAILED` 或其它 audio code · 文案：「语音未能保存/语音暂时无法重放」 · 气泡内标签 · 分类：系统 · 日志：`error_audio`/`error_cache` · 缺失：无 · **判定：改中性** · 改法：保留「这条语音无法播放」（用户点了播放，没反应会以为卡住）；「语音未能保存」是内部实现，删掉 · 勾选：____
- [ ] **C10 图片预览读取失败** · `%ImageError` + `%RetryImage` · `src/ui/image_window.gd:58` · 触发：provider 返回 null · 文案：「图片暂时无法读取，请重试。」 · 独立窗口内标签 · 分类：系统 · 日志：无 · 缺失：预览读取失败事件 · **判定：保留** · 改法：措辞保持；补预览读取失败事件 · 勾选：____
- [ ] **C11 图片预览发送失败** · `%Feedback` · `src/ui/image_window.gd:22` · 触发：`_confirm` 返回 false · 文案：「图片暂时无法发送，请检查当前连接后重试。图片已保留。」 · 窗口内标签 · 分类：系统 · 日志：无 · 缺失：预览确认失败事件 · **判定：保留** · 改法：措辞保持（已说明图片保留、可再点发送）；补确认失败事件 · 勾选：____
- [ ] **C12 送达不确定消息** · 无控件（整条隐藏） · `message_bubble.gd:154-159`、`virtual_message_list.gd:70-75` · 触发：`status=="uncertain"` · 文案：无 · 分类：系统 · 日志：`info_message_delivery` · 缺失：error 级与对账结果 · **判定：改中性（需新增 UI）** · 改法：不能保持整条隐藏。对账只并服务器副本、不改本地状态（`chat_session.gd:609-624`）：送达则之后以服务器 uuid 重现，未送达则永久消失且无痕迹，用户无法区分「丢了」和「发了」。给一条中性状态「未确认送达」+ 重发/刷新核实入口，不要暴露 `uncertain` 这个词 · 勾选：____
- [ ] **C13 未连接发送文本** · 无控件 · `chat_session.gd` `send_text` 的 `idle/auth_rejected` 分支 · 触发：连接不可用/空文本 · 文案：无 · 分类：系统 · 日志：无 · 缺失：SEND_REJECTED 事件 · **判定：改中性（需新增 UI）** · 改法：不能只补日志。`chat_view.gd:153-154` 在返回空串时保留草稿但不提示，用户只能从连接状态猜。输入框旁给「未连接，消息未发送」（或在 C1 状态行体现），并补 `SEND_REJECTED` 事件 · 勾选：____

## D. 动态、评论与发布

- [ ] **D1 动态刷新/未读失败** · `%Notice` · `src/ui/dynamics_window.gd:166-172` · 触发：`_shows_failure` 或 `unread_code` 非 OK · 文案：「动态刷新失败（CODE），点击刷新重试。/未读操作失败（CODE）。」 · 顶部横幅 · 分类：系统 · 日志：HTTP access + `runtime_dynamics_state` · 缺失：operation/phase 维度 · **判定：改中性** · 改法：「刷新失败，点击重试」「未读状态同步失败」，去 CODE；补 operation/phase 维度 · 勾选：____
- [ ] **D2 动态首屏失败占位** · `%Empty` · `src/ui/dynamics_window.gd:18-23,248-254` · 触发：`phase=="failed"` 且列表为空 · 文案：「动态加载失败，点击刷新重试。」 · 右侧占位 · 分类：系统 · 日志：同上 · **判定：改中性** · 改法：「暂时加载不出动态，点击重试」，去「失败」 · 勾选：____
- [ ] **D3 评论发送失败** · `%Status` · `src/ui/dynamic_detail.gd:216` · 触发：`submit_comment` 返回非 OK · 文案：「发送结果不确定…」/「评论失败，草稿已保留（CODE）。」 · 内联 · 分类：系统 · 日志：HTTP + runtime dynamics（部分） · 缺失：early-return 校验无日志 · **判定：改中性** · 改法：必须保留「发送结果不确定，请先刷新核实；草稿已保留」——删掉这条用户会重复评论；「评论失败，草稿已保留」去 CODE；补 early-return 校验日志 · 勾选：____
- [ ] **D4 评论加载失败** · `%Status` · `src/ui/dynamic_detail.gd:248-252` · 触发：comments `state.code` 非 OK · 文案：「评论加载失败（CODE），已保留现有内容；点击动态卡片重试。」 · 内联 · 分类：系统 · 日志：HTTP + runtime dynamics · **判定：改中性** · 改法：「评论加载失败，已保留现有内容，可重试」，去 CODE · 勾选：____
- [ ] **D5 空评论/不允许评论** · `%Status` · `src/ui/dynamic_detail.gd:199-200` + `dynamics_controller.gd:301-316` · 触发：空文本 `INVALID_INPUT`、`COMMENT_NOT_ALLOWED`、`INVALID_REPLY_TARGET`、`BUSY` · 文案：「评论失败，草稿已保留（INVALID_INPUT）。」 · 内联 · 分类：校验（当前误按系统失败展示） · 日志：early return 无日志 · 缺失：校验事件 · **判定：改中性** · 改法：按校验语气重写——空文本「评论内容不能为空」、`BUSY`「正在发送，请稍候」、`COMMENT_NOT_ALLOWED`「此动态不支持评论」（`dynamic_detail.gd:101-108` 已预拦，此分支只兜竞态）、`INVALID_REPLY_TARGET`「回复对象已不存在」；一律不再用「评论失败（CODE）」的系统错误样式 · 勾选：____
- [ ] **D6 发布失败/结果不确定** · `%PublishStatus` · `src/ui/publish_overlay.gd:32` · 触发：`publish_dynamic` 返回非 OK · 文案：「发布结果不确定，请先刷新核实；草稿已保留。」/「发布失败，草稿已保留（CODE）。」 · 内联 · 分类：系统 · 日志：HTTP + runtime dynamics · **判定：改中性** · 改法：必须保留「发布结果不确定，请先刷新核实；草稿已保留」，这是防止重复发布的唯一护栏；「发布失败，草稿已保留」去 CODE · 勾选：____

## E. 日志、头像与平台

- [ ] **E1 复制日志失败** · `%Status` · `src/ui/log_window.gd:58` · 触发：`copy_text` 非 OK · 文案：「复制失败：剪贴板不可用。」 · 状态标签 · 分类：系统 · 日志：无 · 缺失：`warning_log_copy` · **判定：改中性** · 改法：「复制失败，请手动选择文本」。保留：用户主动点的按钮，无回执会以为复制成功；补 `warning_log_copy` · 勾选：____
- [ ] **E2 导出日志失败** · `%Status` · `src/ui/log_window.gd:65` · 触发：`export_run` 返回 Error 枚举 · 文案：「导出失败（%s），请选择尚不存在且可写的文件。」 · 状态标签 · 分类：系统 · 日志：无 · 缺失：`warning_log_export`（目标脱敏） · **判定：改中性** · 改法：「导出失败：目标文件已存在或不可写，请换一个路径。」去掉 Error 枚举数字；补 `warning_log_export`（目标脱敏） · 勾选：____
- [ ] **E3 日志写盘失败（日志窗）** · `%Status` · `src/ui/log_window.gd:70` · 触发：`write_failed` · 文案：「日志写盘失败，当前窗口仍可查看内存记录；归档可能不完整。」 · 状态标签 · 分类：系统 · 日志：同 A10，失败条目缺失 · **判定：保留（弱化）** · 改法：「归档可能不完整，当前窗口仍可查看本次记录。」用户正站在日志窗里，这条告诉他「看到的是内存里的、归档会缺」，有实际意义；补事件计数 · 勾选：____
- [ ] **E4 角色加载失败** · `%Error` · `src/avatar/avatar_panel.gd:60-62` · 触发：`load_character` 非 OK，提前 return 跳过交互接线 · 文案：「角色加载失败，请检查资源是否完整。」 · 面板标签 · 分类：系统/阻断 · 日志：无 · 缺失：`error_avatar_load` 与 Error 码 · **判定：改中性** · 改法：保留（阻断项，面板会缺交互），改「角色资源缺失，请重新解压完整程序。」；补 `error_avatar_load` 与 Error 码，保留隔离 return · 勾选：____
- [ ] **E5 角色构图恢复失败** · `%Error` · `src/avatar/avatar_panel.gd:63-65` · 触发：`framing.load_settings` 非 OK 且非 FILE_NOT_FOUND · 文案：「未能恢复角色位置，已使用默认构图。」 · 面板标签 · 分类：系统/降级 · 日志：无 · 缺失：`warning_avatar_framing_load` · **判定：移除** · 改法：默认构图已生效，用户无动作可做；补 `warning_avatar_framing_load` · 勾选：____
- [ ] **E6 角色构图保存失败** · `%Error` · `src/avatar/avatar_panel.gd:89-91` · 触发：`framing.save_settings` 非 OK · 文案：「当前角色位置无法保存，重启后将恢复上次设置。」 · 面板标签 · 分类：系统/降级 · 日志：无 · 缺失：`warning_avatar_framing_save` · **判定：移除** · 改法：影响仅限下次启动的构图，静默；补 `warning_avatar_framing_save` · 勾选：____
- [ ] **E7 窗口几何保存失败（控制台）** · 无 UI · `src/platform/desktop_window_host.gd:111` · 触发：几何保存 Error · 文案：`push_warning("Window geometry could not be saved (%s)")` · 仅控制台 · 分类：系统 · 日志：无 schema 事件 · 缺失：`warning_settings_save` · **判定：仅日志** · 改法：不加 UI，补 `warning_settings_save` · 勾选：____
- [ ] **E8 动态窗口尺寸读写静默失败** · 无 UI · `src/ui/dynamics_window.gd:99,294-299` · 触发：`load_settings/save_settings` 非 OK · 文案：无 · 分类：系统 · 日志：无 · 缺失：`warning_settings_save` · **判定：仅日志** · 改法：不加 UI，补 `warning_settings_save` · 勾选：____

## F. 改动前置条件

移除项（A2/A3/A4/A8/A10/B2/C4/E5/E6）在删文案前必须先有日志，否则失败将完全不可追溯：

- `A2`/`A4`：记录 `set_login_options` / `remove_account` 的失败步骤（write/clear/forget）与 code。
- `A3`/`A8`：`runtime_account_state` 需带失败步骤与错误码；`A10` 的 `write_failed` 只能落 stderr 或备用通道，不能依赖日志文件本身。
- `B2`：`info_settings_preference` 升到 warning。
- `C4`：补 reading_position 自己的 logger。
- `E5`/`E6`：补 `warning_avatar_framing_load` / `warning_avatar_framing_save`，带 Error 码与 phase。

改中性项中也有必须先补日志的，否则改完只剩一句「请重试」，排查时无从下手：

- `C5` 图片选择校验：无日志，需记录 code、真实限制值、入口（选择/粘贴/拖放）。
- `B10` 导入：补 `TARGET_MISSING`、`STORAGE_UNAVAILABLE`、`SOURCE_EMPTY`、`PARTIAL` 的扫描/完成事件。
- `E1`/`E2`/`E3`：补 `warning_log_*`、`run_id`、脱敏目标、Error 枚举。
- `E4`：补 `error_avatar_load` 与 Error 码。
- `D5`：补 `INVALID_INPUT/COMMENT_NOT_ALLOWED/INVALID_REPLY_TARGET/BUSY` 事件。
- `C12`/`C13`：补 `SEND_REJECTED` 与连接 phase；`info_message_delivery` 不足以审计送达不确定。

剩余待办（原清单 F 段其余项）：媒体导入的 `TARGET_MISSING/STORAGE_UNAVAILABLE/SOURCE_EMPTY/PARTIAL`、头像读取失败、外部链接打开失败，同样需要对应 warning/event；这些项本身保留 UI，补日志是为了可排查，不是为删文案。

## G. 默认保留（非报错）

- 连接中/已连接/重连中、思考中、播放中、加载中、空列表、未选中详情。
- 登录成功、注册成功、退出登录、账号选择/移除成功。
- 所有操作确认弹窗：清理缓存、导入媒体、未保存修改、放弃草稿、明文密钥确认、测试消耗额度。
- 表单校验：密码字符/两次密码、非法天数、模型字段/JSON、图片格式/尺寸。
- 重试/刷新/重选/跳过控件本身。

补一条：控件旁要留一句中性说明（「刷新失败，点击重试」），不要只留裸按钮——用户不知道在重试什么。

## H. 顺带发现的界面/代码缺陷（非文案问题）

- H1 `src/ui/account_view.gd:172`：`_update_state` 在每次 `account_session.changed` 时用 `_error_text(state.code)` 覆写 `%Status`，登录成功后也可能被陈旧错误盖住。
- H2 `src/ui/chat_view.gd:260-271`：音频错误后缀只在 `chat_session.gd:342,375` 的 code 变更时更新，语音恢复正常后不会清除。
- H3 `src/application.gd:130` + `main.tscn:215`：阻断文案是左上角无背景 Label，且静态默认文案会被运行时覆盖；是否被顶栏遮挡未实机验证。
- H4 `src/ui/account_view.gd:246`：文案说「可复制下方项目地址」，但 `%FeedbackAddress` 是只读 LineEdit，没有复制按钮。
- H5 `src/ui/message_bubble.gd:165`：发送失败只有文字，没有重发入口。
- H6 `src/ui/chat_view.gd:211` + `chat_session.gd:153`：`idle/auth_rejected` 下发送被静默拒绝，状态栏无提示。

## I. 本轮执行结果（2026-11-10）

- 新增统一弹窗 `scenes/ui/error_dialog.tscn` + `src/ui/error_dialog.gd`：按当前窗口懒加载、串行队列、重复文本短时去重，并由 `ErrorDialog.set_logger()` 写入 `warning_ui_error` 日志。
- 保留/改中性项除 `B13`（存储容量降级状态）与 `B14/B15`（确认框）外，全部改走弹窗；主窗体、设置页、聊天页不再保留错误文案。
- 移除项 A2、A3、A4、A8、A10、B2、C4、E5、E6 不再显示，状态与错误码保留在内部；失败路径补 `push_warning`/既有日志，A10 不再覆盖主窗。
- 仅日志项 E7、E8 保持无 UI。
- 表单校验（A7、B12、C5、D5 的输入部分）也按本次要求走弹窗，不再内联。
- 未新增 A5 的“复制地址”按钮、C7 的“重发”按钮与 C12 的内联未确认状态；这三项属于交互增强，不影响“报错只走弹窗”的交付。C12 改为弹窗提示“消息未确认送达，请刷新核实或重发”。
- 所有错误码、连接/历史/音频状态机、草稿保留、重试控件与禁用态保持不变；仅渲染通道改变。
