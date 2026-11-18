"""通话记忆工具的授权检索与行动返回值。"""

import hashlib

import src.domain.agent as d
from src.agent.skills.invocation import execution_invocation
from src.agent.skills.memory_retrieval import MemoryQuery
from src.domain.call.omni import MemoryLookupHit, MemoryLookupResult
from src.infrastructure.observability.retrieval_timing import retrieval_call_scope
from src.infrastructure.observability.stage_timing import stage_timing


class LookupCallMemoryHandler:
    def __init__(self, retrieval):
        self._retrieval = retrieval

    async def realize(self, action, context, outputs):
        interaction = context.interaction_context
        if not isinstance(action, d.LookupCallMemory) or interaction is None:
            raise ValueError("memory lookup requires call context")
        identity = interaction.identity
        invocation = execution_invocation(identity.character_id, context, user_id=identity.user_id)
        with retrieval_call_scope(
            context.interaction_id, action.turn_seq, response_id=action.response_id, tool_call_id=action.tool_call_id
        ):
            with stage_timing(f"call:{context.interaction_id}:{action.turn_seq}", "call.v2.retrieval"):
                result = await self._retrieval.search(invocation, query=MemoryQuery((action.query,)))
        if context.cancellation.is_cancelled:
            raise d.SinkRejectedError("cancelled lookup", code=d.SinkRejectionCode.STALE_INTERACTION)
        interaction.call_memory.remember_hits(result.hits)
        hits = tuple(
            MemoryLookupHit(
                hit.memory_record_id or hit.vector_id or hashlib.sha256(hit.rendered_text.encode()).hexdigest(),
                hit.rendered_text,
            )
            for hit in result.hits
        )
        return d.ActionResult(
            action_id=action.action_id,
            status=d.ActionExecutionStatus.COMPLETED,
            error_code=None,
            irreversible_effect_committed=False,
            effect_ref=None,
            value=MemoryLookupResult(hits),
        )
