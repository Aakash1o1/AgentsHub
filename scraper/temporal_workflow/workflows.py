import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.exceptions import ActivityError, is_cancelled_exception

with workflow.unsafe.imports_passed_through():
    from scraper.temporal_workflow.activities import DocumentActivities


@workflow.defn
class DocumentWorkflow:
    BATCH_SIZE = 20
    RETRY = RetryPolicy(initial_interval=timedelta(seconds=2), backoff_coefficient=2, maximum_attempts=5)
    DB_STEP = {"start_to_close_timeout": timedelta(seconds=30), "retry_policy": RETRY}
    WORK_STEP = {"start_to_close_timeout": timedelta(minutes=5), "retry_policy": RETRY}

    CURRENT_ACTIVITY = SearchAttributeKey.for_keyword("CurrentActivity")
    ACTIVITIES_DONE = SearchAttributeKey.for_int("ActivitiesDone")
    ACTIVITIES_LEFT = SearchAttributeKey.for_int("ActivitiesLeft")
    BATCHES = SearchAttributeKey.for_keyword("Batches")

    def __init__(self):
        self.done = 0
        self.planned = None
        self.batches = None

    def show_progress(self, current):
        workflow.upsert_search_attributes([
            self.CURRENT_ACTIVITY.value_set(current) if current else self.CURRENT_ACTIVITY.value_unset(),
            self.ACTIVITIES_DONE.value_set(self.done),
            self.ACTIVITIES_LEFT.value_set(self.planned - self.done) if self.planned is not None
            else self.ACTIVITIES_LEFT.value_unset(),
            self.BATCHES.value_set(self.batches) if self.batches else self.BATCHES.value_unset(),
        ])

    async def step(self, method, args, options):
        self.show_progress(method.__name__)
        result = await workflow.execute_activity_method(method, args=args, **options)
        self.done += 1
        return result

    @workflow.run
    async def run(self, doc_id: int) -> int:
        acts = DocumentActivities

        try:
            await self.step(acts.mark_stage, [doc_id, "extracting"], self.DB_STEP)
            total = await self.step(acts.extract_text, [doc_id], self.WORK_STEP)

            batches = range(0, total, self.BATCH_SIZE)
            self.planned = self.done + 1 + len(batches) + 2
            self.batches = f"0/{len(batches)}"
            await self.step(acts.mark_stage, [doc_id, "embedding"], self.DB_STEP)
            chunks_done = 0
            for number, start in enumerate(batches):
                self.batches = f"{number}/{len(batches)}"
                end = min(start + self.BATCH_SIZE, total)
                chunks_done += await self.step(acts.embed_batch, [doc_id, start, end], self.WORK_STEP)
                workflow.set_current_details(f"Embedding {chunks_done}/{total}")

            self.batches = f"{len(batches)}/{len(batches)}"
            await self.step(acts.finish, [doc_id, "completed"], self.DB_STEP)
            await self.step(acts.announce, [doc_id, "completed"], self.DB_STEP)
            self.show_progress(None)
            return total
        except (ActivityError, asyncio.CancelledError) as e:
            if is_cancelled_exception(e):
                self.planned = self.done + 1
                await self.step(acts.finish, [doc_id, "pending"], self.DB_STEP)
                self.show_progress(None)
                raise
            cause = e.cause or e
            reason = f"{type(cause).__name__}: {cause}"
            self.planned = self.done + 2
            await self.step(acts.finish, [doc_id, "error", reason], self.DB_STEP)
            await self.step(acts.announce, [doc_id, "error", reason], self.DB_STEP)
            self.show_progress(None)
            raise
