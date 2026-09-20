# 客户端窗口重设计 interface

以本文件明确交付的契约替代 README 中冲突的旧窗口呈现。业务协议不变。

## 自绘窗口框架与几何

`scenes/ui/window_chrome.tscn` 为可复用 Control，提供 WindowMinimize/WindowMaximize/WindowClose 三个唯一命名按钮及八个缩放区域。宿主仍为主 SceneTree Window 或业务 Window，设置 borderless；按钮通过宿主 mode 与 close_requested 统一走原有关闭检查。标题栏左键调用 Window.start_drag，双击切换最大化，窗口化状态的八边调用 Window.start_resize。无鼠标事件不得发起系统拖拽。

`WindowChrome.configure(path, key)` 注入独立几何文件与布局键并恢复；`select_layout(key, default_size, minimum)` 先保存旧布局再恢复新布局；`open_window()` 恢复最小化前模式、显示并聚焦。未配置路径不持久化。主窗使用 compact/expanded 两键，日志/动态及其余独立窗使用各自键。持久化节字段 rect:Rect2i、maximized:bool；不存最小化。读损坏/非法字段保留默认值，几何夹至相交最多的显示器可用区，无相交则主屏；零显示器的headless使用调用者提供的默认区域。窗口退出前保存，移动/缩放稳定后延迟保存，文件失败不打断操作且返回可识别Error。

`src/storage/window_geometry.gd` RefCounted：构造(path)；`read_layout(key, fallback:Rect2i, minimum:Vector2i, screens:Array[Rect2i]) -> Dictionary` 返回 rect/maximized；`write_layout(key, rect, maximized) -> Error` 合并其它布局键后写入，不覆盖其他窗口记录。此文件不包含用户内容或凭据。

所有业务窗口具有自绘框架且 force_native=true；日志、动态 transient=false。关闭仍进入宿主已有close_requested，因此有草稿仍需确认，日志关闭只隐藏。测试经场景按钮检查请求与公开几何读写；GPU验证真实mode、拖拽/缩放、焦点和独立性。


## 统一设置窗口

`scenes/ui/settings_window.tscn` / `SettingsWindow` 为唯一设置Window，title=设置，原相处/模型独立Window及其脚本删除，替换为 `preferences_page.tscn` / `model_page.tscn` 的Control。`setup(preferences, models, executor=null)` 显式注入，测试可只注入一个控制器；`select_page("preferences"|"models")` 切换且保留草稿；`open()` 恢复并聚焦；`is_dirty()` 汇总；`is_saving()` 返回当前是否正在保存；`save_changes() -> Dictionary` 异步返回 `{ok, results}`，results按页面/模型用途记录ok/code。不改变PreferencesController和ModelSettings协议。

PreferencesPage.setup(controller)、is_dirty()、save_changes()保存并读取控制器最终状态；ModelPage.setup(settings, executor=null)、is_dirty()、validate_changes()、save_changes()负责全部用途草稿。先逐用途解析JSON并validate，有任何非法草稿时整窗不开始写入；全部有效后按用途顺序保存模型，再保存相处偏好。模型保存成功更新该用途基线；失败不清草稿，仍保存其它独立项。DPAPI失败逐项询问明文，默认取消；拒绝只令该项失败。相处失败仍保留dirty。结果区列清失败页/用途和代码，不宣称事务回滚。

底部保存修改保持窗口打开；关闭有修改时三操作为保存并关闭/放弃/取消，只有全部保存成功且没有dirty才自动关闭。保存期间禁用再次提交和编辑，关闭请求记为待关闭，完成失败则留窗；保存完成发出saving_finished(ok)供应用协调。SettingsWindow transient=true，跟随主窗最小化；重复打开models/preferences导航只切换同一窗口。现有手动模型测试仍单独确认额度，不包含在保存操作里。


### 确认界面全部场景化（用户补充要求）

所有可见UI由Godot控件场景提供，不允许脚本new控件或add_button创建按钮；列表只实例化已有场景。`decision_dialog.tscn` 是内嵌的自绘 Window（非独立业务窗）：公开 dialog_text/ok_button_text/cancel_button_text/show_save 属性，confirmed/canceled/custom_action(action)信号，以及get_ok_button/get_cancel_button。沿用Window.popup_centered/hide，关闭×和Esc发canceled并隐藏，遮罩外点击不关闭；show_save时场景已有的保存并关闭按钮发custom_action("save")。默认焦点取消。替代代码创建的草稿确认框及现有ConfirmationDialog呈现，业务确认逻辑不变。
