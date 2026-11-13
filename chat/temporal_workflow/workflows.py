import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from chat.temporal_workflow.activities import ChatFileSummaryActivities


@workflow.defn
class ChatFileSummaryWorkflow:
    PARALLEL = 4
    RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=5)
    DB_STEP = {"start_to_close_timeout": timedelta(seconds=30), "retry_policy": RETRY}
    WORK_STEP = {"start_to_close_timeout": timedelta(minutes=5), "retry_policy": RETRY}

    async def step(self, method, args, options):
        return await workflow.execute_activity_method(method, args=args, **options)

    @workflow.run
    async def run(self, message_id: int) -> str:
        acts = ChatFileSummaryActivities
        plan = await self.step(acts.read_text, [message_id], self.WORK_STEP)

        total = plan["pieces"]
        notes = []
        for first in range(0, total, self.PARALLEL):
            window = range(first, min(first + self.PARALLEL, total))
            notes += await asyncio.gather(*(
                self.step(acts.summarize_piece, [message_id, index, total], self.WORK_STEP) for index in window
            ))

        summary = await self.step(acts.combine, [message_id, notes, plan["paragraphs"]], self.WORK_STEP)
        await self.step(acts.post_summary, [message_id, summary], self.DB_STEP)
        return summary
