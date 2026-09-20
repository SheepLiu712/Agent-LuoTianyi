# 0.1.2 用户反馈修正 interface

本文件记录用户反馈后交付的增量契约；冲突的旧呈现约定由本文件对应条目替代。业务协议不变。

## 角色默认睁眼与眨眼恢复

AvatarDriver.load_avatar/load_character成功后使用normal表情，正常待机双眼完全睁开；周期性眨眼结束必须恢复。切换表情保留该表情对眼睛的明确配置，例如ease闭眼；回到normal恢复睁眼。语音口型不能改变眼睛规则。加载失败保留当前模型。

AvatarDriver.get_status()增加eye_openness:Vector2，读取实际模型左右眼参数；未加载返回Vector2.ZERO。它是只读状态，不暴露Cubism对象。测试通过此状态观察正常待机、眨眼后恢复、闭眼表情及回到normal。GPU画面单独核查，不以headless代替视觉验收。
