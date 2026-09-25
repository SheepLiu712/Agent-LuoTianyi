"""独立表情恢复行动交付表情及其正常终止。"""

from types import SimpleNamespace

import pytest
from support.routing_support import Sink

import src.domain.agent as d
from src.agent.handlers.action.restore_expression import RestoreExpressionHandler
from src.agent.processing.output_emitter import OutputEmitter

pytestmark = pytest.mark.asyncio


async def test_restore_expression_emits_expression_then_terminal_output():
    action = d.RestoreExpression(
        action_id="restore",
        expression_id="normal",
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
    )
    context = d.ExecutionContext(
        execution_id="execution",
        interaction_id="interaction",
        current_interaction_revision=0,
        cancellation=d.CancellationToken(),
    )
    sink = Sink()

    execution = SimpleNamespace(
        context=context,
        next_sequence=0,
        sink=sink,
        output_started=False,
        agent=SimpleNamespace(_error_code=lambda error, enum: enum.INTERNAL_ERROR,
                              _record_exception=lambda *args: None),
        plan=SimpleNamespace(target_character_id="luotianyi"),
    )
    outputs = OutputEmitter(execution, action.action_id)

    result = await RestoreExpressionHandler().realize(action, context, outputs)

    assert result == d.ActionResult(
        action_id="restore",
        status=d.ActionExecutionStatus.COMPLETED,
        error_code=None,
        irreversible_effect_committed=False,
        effect_ref=None,
    )
    assert len(sink.values) == 2
    assert sink.values[0] == d.ExpressionOutput(
        interaction_id="interaction",
        execution_id="execution",
        action_id="restore",
        sequence_no=0,
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
        expression=d.ChangeExpression(expression_id="normal"),
    )
    assert sink.values[1] == d.MessageEndOutput(
        interaction_id="interaction",
        execution_id="execution",
        action_id="restore",
        sequence_no=1,
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
        status=d.MessageEndStatus.COMPLETED,
        error_code=None,
    )


async def test_restore_expression_handler_rejects_other_action_type():
    action = d.Say(
        action_id="say",
        content="text",
        sound_content=None,
        prepared_audio_ref=None,
        tone=d.Tone(value="normal"),
        expression=None,
        delivery=d.OutputDelivery.CONVERSATION,
    )

    with pytest.raises(TypeError):
        await RestoreExpressionHandler().realize(action, None, None)


async def test_restore_expression_cancellation_emits_nothing():
    action = d.RestoreExpression(
        action_id="restore",
        expression_id="normal",
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
    )
    token = d.CancellationToken()
    token.cancel(d.CancellationReason.NO_LONGER_NEEDED)
    context = d.ExecutionContext(
        execution_id="execution",
        interaction_id="interaction",
        current_interaction_revision=0,
        cancellation=token,
    )
    sink = Sink()
    execution = SimpleNamespace(
        context=context,
        next_sequence=0,
        sink=sink,
        output_started=False,
        agent=SimpleNamespace(_error_code=lambda error, enum: enum.INTERNAL_ERROR,
                              _record_exception=lambda *args: None),
        plan=SimpleNamespace(target_character_id="luotianyi"),
    )

    result = await RestoreExpressionHandler().realize(
        action,
        context,
        OutputEmitter(execution, action.action_id),
    )

    assert result.status is d.ActionExecutionStatus.CANCELLED
    assert result.error_code is d.ExecutionErrorCode.CANCELLED
    assert sink.values == []
