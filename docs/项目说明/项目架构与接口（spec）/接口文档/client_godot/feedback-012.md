# 0.1.2 用户反馈修正 interface

本文件记录用户反馈后交付的增量契约；冲突的旧呈现约定由本文件对应条目替代。业务协议不变。

## 角色默认睁眼与眨眼恢复

AvatarDriver.load_avatar/load_character成功后使用normal表情，正常待机双眼完全睁开；周期性眨眼结束必须恢复。切换表情保留该表情对眼睛的明确配置，例如ease闭眼；回到normal恢复睁眼。语音口型不能改变眼睛规则。加载失败保留当前模型。

AvatarDriver.get_status()增加eye_openness:Vector2，读取实际模型左右眼参数；未加载返回Vector2.ZERO。它是只读状态，不暴露Cubism对象。测试通过此状态观察正常待机、眨眼后恢复、闭眼表情及回到normal。GPU画面单独核查，不以headless代替视觉验收。

## 角色视线与触摸

AvatarDriver.set_gaze(target:Vector2)接收[-1,1]的视线目标，非有限数值忽略；按旧端60Hz下0.15插值平滑、写ParamEyeBallX/Y，get_status增加gaze:Vector2实际眼球参数。AvatarPanel从本区域鼠标位置换算目标，鼠标离开或窗口失焦回正；右键拖动不触摸。

AvatarDriver.hit_test(local_position:Vector2)->Array[String]只在真实可见模型三角形命中时返回去重头/手/身体；局部坐标由视图变换，缩放/拖动后仍对应实际绘制。部件表保存在角色映射资源，按本项目Moc文件的Cubism Core drawable-parentPart关系生成，引用原端Part24/8/11、Part21及两组Skinning、Part18/17；不使用包围角色的大矩形，不新增Cubism原生接口。

AvatarPanel.touched(areas:Array[String])只在左键命中时发出，同时实例化touch_ripple.tscn：Panel圆环、忽略鼠标、半径渐变至60、0.5秒淡出并释放。固定UI仍由场景承载。

Application把touched连接ChatSession.record_touch(areas:Array[String])->void。会话ready且在线音频未播放才累计，最多每秒一次、点击触发合并上报；不改变旧端瞬时user_touch协议，payload为touchArea数组、touchCount、timeSinceLastSentTouch秒数，durable=false。在线音频期间不计数、不发送但本地圆环正常；本地重放不禁止触摸；断线/退出清理累计，禁止跨账号延迟发送。测试覆盖真实网格命中、离开回正、原协议内容/节流及语音抑制。
