# 客户端窗口重设计 interface

以本文件明确交付的契约替代 README 中冲突的旧窗口呈现。业务协议不变。

## 自绘窗口框架与几何

`scenes/ui/window_chrome.tscn` 为可复用 Control，提供 WindowMinimize/WindowMaximize/WindowClose 三个唯一命名按钮及八个缩放区域。宿主仍为主 SceneTree Window 或业务 Window，设置 borderless；按钮通过宿主 mode 与 close_requested 统一走原有关闭检查。标题栏左键调用 Window.start_drag，双击切换最大化，窗口化状态的八边调用 Window.start_resize。无鼠标事件不得发起系统拖拽。

`WindowChrome.configure(path, key)` 注入独立几何文件与布局键并恢复；`select_layout(key, default_size, minimum)` 先保存旧布局再恢复新布局；`open_window()` 恢复最小化前模式、显示并聚焦。未配置路径不持久化。主窗使用 compact/expanded 两键，日志/动态及其余独立窗使用各自键。持久化节字段 rect:Rect2i、maximized:bool；不存最小化。读损坏/非法字段保留默认值，几何夹至相交最多的显示器可用区，无相交则主屏；零显示器的headless使用调用者提供的默认区域。窗口退出前保存，移动/缩放稳定后延迟保存，文件失败不打断操作且返回可识别Error。

`src/storage/window_geometry.gd` RefCounted：构造(path)；`read_layout(key, fallback:Rect2i, minimum:Vector2i, screens:Array[Rect2i]) -> Dictionary` 返回 rect/maximized；`write_layout(key, rect, maximized) -> Error` 合并其它布局键后写入，不覆盖其他窗口记录。此文件不包含用户内容或凭据。

所有业务窗口具有自绘框架且 force_native=true；日志、动态 transient=false。关闭仍进入宿主已有close_requested，因此有草稿仍需确认，日志关闭只隐藏。测试经场景按钮检查请求与公开几何读写；GPU验证真实mode、拖拽/缩放、焦点和独立性。
