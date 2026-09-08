# Stage 与 WebSocket adapter 开发规划完成记录

## 本轮范围

保留生产 ChatStream 聊天入口，完成独立 Stage、StageManager、共享 adapter 和可接入的网络接收接口。文本 handler 在集成测试中提供；生产刺激路由登记交互结束 handler。

## 已完成

1. StageOutput 定义 Agent 业务输出、呈现状态变化和取消投递命令。
2. adapter 收敛为 submit_output、receive_event、bind、disconnect；输入和输出协议分别封装在 _input.py、_protocol.py。
3. ChatStage 拥有唯一刺激和输出 sink，维护 pending、快照、回复期限、计划与两条串行处理链。
4. StageManager 管理用户和角色交互、重连保留、离线结束与系统关闭。
5. InteractionEnding 及 Agent handler 完成交互 context 释放。
6. SAY 的 TTS、预制音频、Delivery 和空取消终止包转换保持客户端协议兼容；App 按可选 packet_sequence 区分内容相同的合法音频块。
7. 测试覆盖真实 Agent/SAY 协议、真实 WebSocket、Stage 接入到音频包、并发与取消、失败收尾、重连和回收。

接口事实见 [adapter](README.md) 和 [Stage](../stage/README.md)。
