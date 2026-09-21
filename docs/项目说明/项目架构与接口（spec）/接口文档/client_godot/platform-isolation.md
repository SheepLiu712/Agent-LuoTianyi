# 客户端平台隔离与扩展接口

2026-09-21 用户批准；仅 Godot 客户端、测试和文档。本轮不改协议、外观、版本或原生 DLL，不打包、不推送。本文替代旧文档中业务/UI直接使用文件路径、原生类型、平台 API 的装配约定。

## 依赖与兼容

UI → 应用协调/业务控制器 → 注入的能力接口 → Godot/平台实现。控件、场景、信号、计时和绘制仍直接使用 Godot；OS、DisplayServer、文件 I/O、平台探测和原生 ClassDB 创建只能出现在能力实现内。禁止全局服务定位器和万能平台服务。正式功能不得依赖 preview；固定可见节点仍由 tscn 提供。

地址规范化归入纯 `ServerAddress.normalize(address)->String`，逐字保留既有接受/拒绝规则。`AccountScope.key(server,username)->String` 使用规范化地址的 JSON `[server,username]` SHA-256；凭据、模型、音频、图片、阅读位置原目录/键/格式保持兼容。旧 AccountApi.normalize_server 与未使用 ChatSession.get_log_directory 删除，调用者和测试迁到新公开入口。

## 当前能力接缝

- SettingsStore：读取/写入指定逻辑设置组，返回 data 与 Error；实现保留旧 ConfigFile 格式及不同配置文件边界。UI只传设置值，不操作文件或平台路径。
- InputService：读取剪贴板图片、复制文本、查询 IME 合成状态；不可用返回空图片/明确 Error/false，不吞掉普通文本粘贴。控件自身 has_ime_text 仍同时参与防误发。
- FileInteraction：由场景提供原生 FileDialog，实现连接其选择/取消；图片结果为 `{ok,code,bytes,mime}`，失败/取消不清已有附件。导出目的地为受控句柄，日志写入由句柄交给存储实现，不让 UI 处理平台路径。请求取消及旧账号回调不得更新新页面。
- ReadStream：get_buffer(size)、get_length/get_position、close；关闭幂等。缓存提供流而不向播放器暴露 FileAccess。播放器停止、失败和切账号必须关闭流。
- PasswordEncryption.encrypt_password 与 SecretProtection.protect_secret/unprotect_secret 沿用现有字节结果契约；Windows 实现委托既有 DLL，缺失返回错误，不自动降级。认证不可用禁止登录，日志/反馈仍可访问。
- DecoderFactory.create_decoder 返回统一 decoder（append/finish/read_frames/get_status/get_amplitude/get_waveform）；缺失返回 null。在线和重放均使用工厂，缺失仍保留聊天正文并完成错误生命周期。
- AvatarDriver 保留 load_character/load_avatar/apply_expression/play_motion/set_mouth_openness/set_gaze/hit_test/get_status；Cubism 子实现负责资源和原生对象，失败不替换已有模型。UI只依赖项目驱动语义。
- WindowHost 负责桌面窗口外观、模式、屏幕范围、焦点、拖动和原生归属；窗口协调负责复用、草稿和图片来源。RuntimeEnvironment 负责启动参数、headless、日志注册和运行环境信息；平台选择仅发生在组装实现。
- StorageService 登录/磁盘契约不变，bytes/未知 -1 不变；外链继续独立。其他领域存储保留职责，平台实现不渗入消费者。

所有依赖由创建者注入；独立预览/场景启动的具体默认装配位于专门 composition 实现，不在业务方法中寻找全局服务。Application 分为服务组装、账号生命周期、窗口协调，窗口确认/保存等待/日志跨退出保留等行为不变。

## 未来扩展（仅接口，不实现功能）

AppearanceService、WorldService、DeviceService 相互独立。共同提供 get_capabilities()->Dictionary、start(context)->Error、cancel(request_id)->void、stop()->void。context 仅 scope_id:String、generation:int、character_id:String；不得携带认证材料或平台对象。stop 幂等并释放本账号请求/订阅/设备连接，旧代次结果不得向新账号投递。

- AppearanceService.request_change(request_id,character_id,resource_id,origin)->Dictionary，origin 为 user/ai；get_state()->Dictionary；completed(request_id,result)、state_changed(state)。实际失败保留原外观。
- WorldService.apply_state(state)->Dictionary、request_action(request_id,action)->Dictionary；interaction_received(event)、completed(request_id,result)。state/action/event 为该模块不透明数据，不规定场景格式。
- DeviceService.request_control(request_id,device_id,intent)->Dictionary；state_changed(state)、event_received(event)、completed(request_id,result)。不规定连接协议或硬件命令格式。

请求立即结果 `{ok,code}`；接受仅表示已受理（ACCEPTED），完成经 completed 且同请求至多一次。未实现默认类 start 返回 ERR_UNAVAILABLE，请求返回 `{ok:false,code:NOT_IMPLEMENTED}`，能力均 false，状态为空；不留请求、不触发完成、不建立任务/连接。数据入出深拷贝；取消无已知请求无副作用。不增加导航入口，不把世界/设备事件转换成聊天文本，不更改服务端。

## 清理证据与保留项

| 对象 | 处理 | 依据 |
| --- | --- | --- |
| WindowAction/WindowClose 和 WindowNormal/WindowHover/CloseHover | 删除 | 仅主题内部引用，无场景/脚本消费者 |
| ChatSession.get_log_directory | 删除 | 日志现由独立窗口展示，方法无消费者 |
| preview/composer_input、preview/message_bubble | 移入 ui，保留 UID | 正式聊天和预览共同使用 |
| WindowChrome、Frost、隐藏状态节点 | 保留/迁移能力实现 | 几何、磨砂及登录/错误等现行状态需要 |
| 离线聊天、独立角色预览 | 保留 | 独立验收入口，不是废弃业务 |
| 当前混合 DLL | 保留 | 本轮只隔离各能力接口，不拆构建产物 |

## 验证

四组默认检查、设置/登录/下拉/气泡/角色/原生窗口 GPU 验证建立前后基线；能力替换通过 Fake 外部实现验证，不 mock 内部实现步骤。检查旧配置与 scope 哈希兼容、取消/资源释放、账号隔离、缺失能力局部降级。架构检查验证禁止调用/依赖方向及删除路径无引用。纯迁移使用回归及静态证据，不伪造 Red。Android、真实系统 DPI、多屏及公共服务未经真机验证不得声称支持。

### 当前注入调用形式

- SettingsStore.load_settings/save_settings()->Error、get_value(section,key,fallback)、set_value(section,key,value)。GodotSettingsStore保留原配置格式，临时文件成功后替换，不改变旧路径。AvatarFraming(settings=null) 的 load_settings/save_settings 不再接收路径；DynamicsWindow.setup(controller,settings_store=null)；场景默认资源以 resource_local_to_scene 隔离。
- FileInteraction.bind(FileDialog)、select_image()、select_export(filename)、cancel()；image_selected(result)、export_selected(target)、canceled。ImageAttachment删除from_file，仅校验from_bytes/from_image；文件读取在ImageFileReader。导出目标export_log(logger,run_id)->Error，平台路径封装在目标内。
- ReplyAudio(logger=null,clock=Callable(),cache=null,decoder_factory=null)，未注入工厂明确解码不可用；正式组装与真实音频测试显式注入工厂。AudioCache.open_stream(id)->RefCounted仅打开本账号已完整校验缓存，失败null；播放器拥有并关闭流。
