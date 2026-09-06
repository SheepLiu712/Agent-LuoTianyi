"""输出公开契约的样例；RED 桥接只让旧生产协议进入可观察行为。"""
from dataclasses import replace
import importlib

import src.domain.agent as d
from routing_support import completed, plan_and_context


def draft(kind, action, context, **changes):
    """GREEN 移除旧对象分支；不以不存在的私有草稿导入制造 RED。"""
    values = {
        "TextFinal": dict(text="原始文字"),
        "AudioChunk": dict(data=b"RIFF\x00\xff\x10\x80WAVE", framing=d.AudioFraming.FILE_FRAGMENT),
        "MessageEnd": dict(status=d.MessageEndStatus.FAILED, error_code=d.AudioErrorCode.EMPTY_AUDIO),
        "Expression": dict(expression=d.ChangeExpression(expression_id="happy")),
    }[kind] | dict(delivery=d.OutputDelivery.CONVERSATION) | changes
    try:
        drafts = importlib.import_module("src.agent.outputs.drafts")
    except ModuleNotFoundError as error:
        if error.name not in {"src.agent.outputs", "src.agent.outputs.drafts"}:
            raise
        return getattr(d, kind + "Output")(
            **values, interaction_id=context.interaction_id, execution_id=context.execution_id,
            action_id=action.action_id, sequence_no=0,
        )
    return getattr(drafts, kind + "Draft")(**values)


def fresh(context, **changes):
    return replace(context, cancellation=d.CancellationToken(), **changes)


def single():
    plan, context = plan_and_context()
    return replace(plan, actions=plan.actions[:1]), context


def failed(action, *, cancelled=False, effect=False):
    return completed(action,
        status=d.ActionExecutionStatus.CANCELLED if cancelled else d.ActionExecutionStatus.FAILED,
        error_code=d.ExecutionErrorCode.CANCELLED if cancelled else d.ExecutionErrorCode.PROVIDER_TIMEOUT,
        irreversible_effect_committed=effect,
        effect_ref=d.EffectRef(kind=d.EffectKind.DYNAMIC_POST, effect_id="effect") if effect else None,
    )


def accepted(value):
    return d.OutputReceipt(execution_id=value.execution_id, sequence_no=value.sequence_no,
                           status=d.OutputAcceptanceStatus.ACCEPTED)


async def reject(value):
    raise d.SinkRejectedError("private receiver content", code=d.SinkRejectionCode.BACKPRESSURE_TIMEOUT)


async def no_reentry(action, context, outputs):
    # 再进入会产生公开可见的失败，而不是断言私有协作次数。
    raise AssertionError("settled handler must not run again")
