"""输出公开契约的内容样例。"""
from dataclasses import replace
from src.agent.processing import output_drafts as drafts

import src.domain.agent as d
from routing_support import completed, plan_and_context


def draft(kind, action, context, **changes):
    """构造处理器内容草稿，由 Agent 绑定身份。"""
    values = {
        "TextFinal": dict(text="原始文字"),
        "AudioChunk": dict(data=b"RIFF\x00\xff\x10\x80WAVE", framing=d.AudioFraming.FILE_FRAGMENT),
        "MessageEnd": dict(status=d.MessageEndStatus.FAILED, error_code=d.AudioErrorCode.EMPTY_AUDIO),
        "Expression": dict(expression=d.ChangeExpression(expression_id="happy")),
    }[kind] | dict(delivery=d.OutputDelivery.CONVERSATION) | changes
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
