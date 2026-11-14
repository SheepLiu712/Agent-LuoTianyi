"""Stage-owned threshold maintenance, separate from foreground output execution."""

import asyncio
from collections import deque
from uuid import uuid4

import src.domain.agent as d

from ._sinks import _NoOutputSink


class ThresholdMaintenance:
    def __init__(self, stage):
        self.stage = stage
        self.pending = deque()
        self.task = None
        self.execution = None

    @staticmethod
    def accepts(plan):
        return (
            len(plan.actions) == 1
            and isinstance(plan.actions[0], d.CognitiveMaintenance)
            and plan.actions[0].reason is d.MaintenanceReason.COMPACTION_THRESHOLD
        )

    def enqueue(self, plan, token):
        self.pending.append((plan, token))
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._run(), name="stage-threshold-maintenance")

    def cancel(self):
        self.pending.clear()
        if self.execution is not None:
            self.execution.cancellation.cancel(d.CancellationReason.NO_LONGER_NEEDED)
        if self.task is not None and not self.task.done():
            self.task.cancel()
        return self.task

    async def _run(self):
        while self.pending:
            plan, token = self.pending.popleft()
            report = None
            try:
                if token.is_cancelled:
                    continue
                self.execution = d.ExecutionContext(
                    execution_id=str(uuid4()),
                    interaction_id=self.stage.interaction_id,
                    current_interaction_revision=self.stage._revision,
                    cancellation=d.CancellationToken(),
                    interaction_context=self.stage.context,
                )
                report = await self.stage._agent.realize_action_plan(plan, self.execution, _NoOutputSink())
                if report.status is not d.ExecutionStatus.COMPLETED:
                    self.stage._logger.error(
                        "Stage threshold maintenance failed interaction=%s code=%s",
                        self.stage.interaction_id,
                        report.error_code,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                self.stage._logger.exception(
                    "Stage threshold maintenance failed interaction=%s", self.stage.interaction_id
                )
            finally:
                self.execution = None
                self.stage._on_execution_finished(plan, report)
