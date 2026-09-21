# 客户端窗口重设计 interface

平台能力与当前装配签名已由[平台隔离契约](platform-isolation.md)替代；本文保留对应业务与视觉行为，旧路径/直接平台调用不再作为实现要求。

2026-09-21用户反馈后的系统窗框、Godot圆角、模型卡片、图片发送、语音缓存与StorageService，以[反馈修正interface](feedback-012.md)为准。下面相冲突的自绘标题栏与旧入口条目保留为本轮实现历史，已被替代。

以本文件明确交付的契约替代 README 中冲突的旧窗口呈现。业务协议不变。

## 自绘窗口框架与几何（自绘部分已被系统窗框替代）

`scenes/ui/window_chrome.tscn` 为可复用 Control，提供 WindowMinimize/WindowMaximize/WindowClose 三个唯一命名按钮及八个缩放区域。宿主仍为主 SceneTree Window 或业务 Window，设置 borderless；按钮通过宿主 mode 与 close_requested 统一走原有关闭检查。标题栏左键调用 Window.start_drag，双击切换最大化，窗口化状态的八边调用 Window.start_resize。无鼠标事件不得发起系统拖拽。

`WindowChrome.configure(path, key)` 注入独立几何文件与布局键并恢复；`select_layout(key, default_size, minimum)` 先保存旧布局再恢复新布局；`open_window()` 恢复最小化前模式、显示并聚焦。未配置路径不持久化。主窗使用 compact/expanded 两键，日志/动态及其余独立窗使用各自键。持久化节字段 rect:Rect2i、maximized:bool；不存最小化。读损坏/非法字段保留默认值，几何夹至相交最多的显示器可用区，无相交则主屏；零显示器的headless使用调用者提供的默认区域。窗口退出前保存，移动/缩放稳定后延迟保存，文件失败不打断操作且返回可识别Error。

`src/storage/window_geometry.gd` RefCounted：构造(path)；`read_layout(key, fallback:Rect2i, minimum:Vector2i, screens:Array[Rect2i]) -> Dictionary` 返回 rect/maximized；`write_layout(key, rect, maximized) -> Error` 合并其它布局键后写入，不覆盖其他窗口记录。此文件不包含用户内容或凭据。

所有业务窗口具有自绘框架且 force_native=true；日志、动态 transient=false。关闭仍进入宿主已有close_requested，因此有草稿仍需确认，日志关闭只隐藏。测试经场景按钮检查请求与公开几何读写；GPU验证真实mode、拖拽/缩放、焦点和独立性。


## 统一设置窗口

`scenes/ui/settings_window.tscn` / `SettingsWindow` 为唯一设置Window，title=设置，原相处/模型独立Window及其脚本删除，替换为 `preferences_page.tscn` / `model_page.tscn` 的Control。当前`setup(preferences, models, executor=null, clear_cache=Callable(), storage_service=null, cache_directory="")`显式注入，测试可只注入一个控制器；`select_page("preferences"|"models"|"audio")`切换且保留草稿，缓存页不参与设置dirty及保存；`open()`恢复并聚焦；`is_dirty()`汇总；`is_saving()`返回当前是否正在保存；`save_changes() -> Dictionary`异步返回`{ok, results}`，results按页面/模型用途记录ok/code。新增`logout_requested()`由底部退出登录发出，Application接入统一退出；UI不直接登出。不改变PreferencesController和ModelSettings协议。缓存依赖及状态呈现细节见[反馈修正](feedback-012.md)。

PreferencesPage.setup(controller)、is_dirty()、save_changes()保存并读取控制器最终状态；ModelPage.setup(settings, executor=null)、is_dirty()、validate_changes()、save_changes()负责全部用途草稿。先逐用途解析JSON并validate，有任何非法草稿时整窗不开始写入；全部有效后按用途顺序保存模型，再保存相处偏好。模型保存成功更新该用途基线；失败不清草稿，仍保存其它独立项。DPAPI失败逐项询问明文，默认取消；拒绝只令该项失败。相处失败仍保留dirty。结果区列清失败页/用途和代码，不宣称事务回滚。

底部保存修改保持窗口打开；关闭有修改时三操作为保存并关闭/放弃/取消，只有全部保存成功且没有dirty才自动关闭。保存期间禁用再次提交和编辑，关闭请求记为待关闭，完成失败则留窗；保存完成发出saving_finished(ok)供应用协调。SettingsWindow transient=true，跟随主窗最小化；重复打开models/preferences导航只切换同一窗口。现有手动模型测试仍单独确认额度，不包含在保存操作里。


### 确认界面全部场景化（用户补充要求）

所有可见UI由Godot控件场景提供，不允许脚本new控件或add_button创建按钮；列表只实例化已有场景。`decision_dialog.tscn` 是内嵌的自绘 Window（非独立业务窗）：公开 dialog_text/ok_button_text/cancel_button_text/show_save 属性，confirmed/canceled/custom_action(action)信号，以及get_ok_button/get_cancel_button。沿用Window.popup_centered/hide，关闭×和Esc发canceled并隐藏，遮罩外点击不关闭；show_save时场景已有的保存并关闭按钮发custom_action("save")。默认焦点取消。替代代码创建的草稿确认框及现有ConfirmationDialog呈现，业务确认逻辑不变。


## 动态内发布浮层

`publish_overlay.tscn` 取代publish_window.tscn；根Control挂publish_overlay.gd，固定遮罩、居中卡片、PublishDraft/PublishButton/状态/取消/关闭及DiscardDialog均为场景节点。setup(controller)、published(id)、is_dirty()、open()和close_requested信号保留业务调用约定；open聚焦草稿；关闭/取消/Esc同一路径，非空或写入中需放弃确认，点击遮罩不关闭。取消确认保留文字和浮层；发布失败保留正文、成功发published并释放浮层。DynamicsWindow仍是独立原生窗口，只维护一个浮层，不新增原生发布窗口；关闭动态的dirty包含发布和所有已打开评论页，确认后释放整个子树。


## 全局图片窗口与来源归属

`ImagePresenter(geometry_path)` 为Application/离线入口各自唯一的非可见Node服务；`open_image(source:Window, provider:Callable, confirm:Callable=Callable()) -> Window` 从image_window.tscn创建或复用一个原生Window，provider每次调用返回Texture2D或null（null显示错误与重试），可选confirm只用于离线待发送图片，用户确认时返回bool，false保留预览、true关闭。不得后台自动发送。`close()`清空纹理/回调并隐藏。

ImageWindow.present(source,provider,confirm)把窗口转属当前source；重用时换图重置适应窗口，保留已保存窗口几何。所有图片控件、错误/重试、适应/原始比例、缩放、关闭和离线确认按钮在场景里。窗口跟随当前source最小化/恢复；关闭来源销毁其图片窗，旧来源关闭不影响已转属图片；显式关闭回到来源窗口及此前焦点，不修改阅读位置。只保存窗口几何，不持久化图片来源/草稿/回调。

ChatView新增image_requested(provider)信号，图片UI只向Application请求展示；失败时原图重试调用原会话图片接口。Application注入唯一presenter并在退出账号时清空。离线样板也改用同一ImagePresenter契约，其模拟图片确认继续保留失败反馈；旧image_overlay脚本及场景移除。


## 主导航与一次性草稿汇总

main.tscn的NavChat/NavDynamics/NavSettings/NavLogs为四个文字居中的固定场景控件；登录后显示窄导航，登录前保留账户页日志入口。AccountMenu及装配已删除，退出登录仅由设置底部请求；退出应用使用主窗系统关闭。ChatView移除已被导航替代的logout_requested/log_requested/settings_requested/set_dynamics_unread，is_dirty()观察未发送文字及图片附件；原CacheButton已由设置语音缓存页替代。导航动态按钮显示99+上限，根Split按自身可用宽度恢复45:55。

主窗关闭/退出账号汇总聊天输入、设置及动态草稿，只有一个ExitDialog，列名称而不回显敏感正文；返回继续编辑保留全部状态，放弃则关闭业务窗口并清草稿，日志不随退出账号关闭。设置正在保存时先等待saving_finished再重新判断，不并发销毁保存流程或自动发送文字。重复设置导航只恢复聚焦，不重置当前设置页。

登录/注册/重置模式提供场景BackToLogin按钮，回到登录不触发网络操作；紧凑页用滚动容器承载较长表单。日志和动态独立，统一设置transient跟随主窗，系统关闭与应用内关闭入口请求同一关闭流程。


## 现代主题、磨砂与可见控件约束

主题新增AppSurface、TerminalSurface、WindowAction/WindowClose、NavigationButton，保留#66CCFF与15px正文、焦点描边和语义色。主要控件至少36px，主聊天边距24/间距16/头像40/输入最小96，气泡内边距16圆角12；日志工具栏浅色，RichTextLabel正文用深色TerminalSurface。相关UI场景测试更新已批准的字面规格，不沿用旧22px边距等约束。

frost_surface.tscn 为ColorRect控件配合屏幕纹理mipmap连续模糊ShaderMaterial；只读取所在Viewport已绘制的应用画面。标题栏和导航使用浅色tint，发布遮罩使用深色tint；文字在其后绘制而保持清晰。headless、未知renderer或场景blur_enabled=false时去掉材质使用同配色实底。资源不采样桌面，无原生DWM依赖。效果与fallback均由固定控件承载。

设置窗口在最小720×640下，内容页可垂直滚动且不遮挡固定底部操作栏；相处页的补充上下文和重新加载操作仍可通过滚动/键盘焦点到达。滚动容器和表单均在场景中定义，不改设置控制器接口。

语音波形使用waveform_strip.tscn中的24个预置CenterContainer/ColorRect，替代_draw/draw_line；脚本仅依据values/progress更新可见、高度和已播色，保留已有数据字段。禁止产品UI脚本new控件、add_button或代码建树，重复内容仅实例化场景。补充测试检查材质/fallback、预置波形及主题语义；GPU截图与帧时间记录验证实际渲染，不把headless当视觉证据。


### 原生验证后的平台约束（自绘操作记录已被系统窗框替代）

自绘标题栏统一48px；左键移动超过4px才调用系统拖拽，防止单击误启动拖动。无边框铺满屏幕时本引擎可能返回FULLSCREEN而非MAXIMIZED，框架统一识别为展开状态并保留原始矩形以还原。恢复最小化的子窗口先重建可见表面，主Window禁止hide，走mode恢复；所有关闭请求先保存几何再进入业务确认。

本引擎的非模态transient不必对应Win32 GW_OWNER，不能依此代替行为验收。设置显式监听主窗mode并保存自身此前可见状态后隐藏/恢复；图片依据当前来源做同样联动。原生测试实际核查可见性；动态/日志仍核查无owner和独立任务栏资格。未增加DWM、原生扩展或引擎窗口回调覆盖。
