# 单次处理的输入范围

Stage 在 HandleStimulusRequest 中确定本次 pending_stimuli 和 prepared_inputs。Agent 直接路由 handle，不保存输入归属或安排回复计时。

原始内容由预处理 handler 处理一条；InteractionDeadline 由回复 handler 处理有序批次；purpose=REFLECT 由 reflection handler 处理已消费部分。处理器通过 PlanEmitter.context 借用 Stage 的上下文。

实现入口见 [处理器路由](handler-routing.md)、[Stage 调度](../stage/README.md) 和 [输入契约](../domain/handle-input.md)。
