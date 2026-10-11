from types import SimpleNamespace

import pytest

import src.domain.agent as d
from src.agent.handlers.action.say import SayHandler
from src.agent.processing.execution import Execution
from src.domain.call import CallAudioRoute, CallSpeechDelivery


class Stream:
    def __init__(self):
        self.values = iter((SimpleNamespace(data=b"pcm!", framing=d.AudioFraming.FILE_FRAGMENT),))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.values)
        except StopIteration as error:
            raise StopAsyncIteration from error

    async def aclose(self):
        return None


class Speaking:
    def speak(self, invocation, *, text, tone, output_format=None):
        del invocation, text, tone
        assert output_format == d.CALL_PCM_FORMAT
        return Stream()


class Permit:
    def allows(self, response_id):
        return response_id == "response-1"


class Sink:
    def __init__(self):
        self.outputs = []

    async def emit(self, output):
        self.outputs.append(output)
        return d.OutputReceipt(
            execution_id=output.execution_id,
            sequence_no=output.sequence_no,
            status=d.OutputAcceptanceStatus.ACCEPTED,
        )


@pytest.mark.asyncio
async def test_real_say_handler_propagates_call_metadata_to_every_output():
    delivery = CallSpeechDelivery(
        audio_route=CallAudioRoute.CALL,
        display_in_chat=False,
        is_ephemeral=True,
        provisional=True,
        response_id="response-1",
    )
    action = d.Say(
        action_id="say-1",
        content="不显示",
        sound_content="你好",
        prepared_audio_ref=None,
        tone=d.Tone(value="normal"),
        expression=d.ChangeExpression(expression_id="smile"),
        delivery=d.OutputDelivery.EPHEMERAL_REACTION,
        call_delivery=delivery,
    )
    plan = d.ActionPlan(
        plan_id="plan-1",
        origin_request_id="request-1",
        plan_ordinal=0,
        target_character_id="luotianyi",
        interaction_id="call-1",
        basis_interaction_revision=0,
        source_stimulus_ids=("stimulus-1",),
        actions=(action,),
    )
    context = d.ExecutionContext(
        execution_id="execution-1",
        interaction_id="call-1",
        current_interaction_revision=0,
        cancellation=d.CancellationToken(),
        call_output_permit=Permit(),
    )
    sink = Sink()
    handler = SayHandler("luotianyi", Speaking(), SimpleNamespace())
    agent = SimpleNamespace(
        _action_router=SimpleNamespace(resolve=lambda _kind: handler),
        _error_code=lambda error, enum: enum.INTERNAL_ERROR,
        _record_exception=lambda *args: None,
        _action_result=lambda item: d.ActionResult(
            action_id=item.action_id,
            status=d.ActionExecutionStatus.FAILED,
            error_code=d.ExecutionErrorCode.INTERNAL_ERROR,
            irreversible_effect_committed=False,
            effect_ref=None,
        ),
        _execution_report=lambda *args: d.ExecutionReport(
            plan_id=plan.plan_id,
            execution_id=context.execution_id,
            status=args[2],
            error_code=args[3],
            action_results=tuple(args[4]),
            output_started=args[5],
            retryable=args[6],
        ),
    )

    report = await Execution(agent, plan, context, sink).run()

    assert report.status is d.ExecutionStatus.COMPLETED
    assert [type(output) for output in sink.outputs] == [
        d.TextFinalOutput,
        d.ExpressionOutput,
        d.AudioChunkOutput,
        d.MessageEndOutput,
    ]
    assert all(output.call_delivery == delivery for output in sink.outputs)
    assert sink.outputs[0].text == "不显示"
    audio = sink.outputs[2]
    assert audio.framing is d.AudioFraming.RAW_PCM
    assert audio.audio_format == d.CALL_PCM_FORMAT
    assert audio.final is True


def test_chat_output_metadata_defaults_remain_unchanged():
    output = d.AudioChunkOutput(
        interaction_id="chat-1",
        execution_id="execution-1",
        action_id="say-1",
        sequence_no=0,
        delivery=d.OutputDelivery.CONVERSATION,
        data=b"audio",
        framing=d.AudioFraming.COMPLETE_FILE,
    )
    assert output.call_delivery == CallSpeechDelivery()
