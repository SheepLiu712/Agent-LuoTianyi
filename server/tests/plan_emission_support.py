"""计划投递的内部草稿样例；结果从公开 handle 观察。"""

from src.agent.processing.plan_emitter import ActionPlanDraft
import src.domain.agent as d
from routing_support import settlement


def draft(*, text="计划正文", actions=None, sources=("m2", "m1")):
    values = dict(source_stimulus_ids=sources, actions=actions if actions is not None else (
        d.Say(action_id="say", content=text, sound_content=None, prepared_audio_ref=None,
              tone=d.Tone(value="normal"), expression=None, delivery=d.OutputDelivery.CONVERSATION),
    ))
    return ActionPlanDraft(**values)


async def one_plan(req, plans):
    receipt = await plans.emit(draft())
    return settlement(req, emitted=(receipt.plan_id,))
