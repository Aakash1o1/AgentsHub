from asgiref.sync import async_to_sync
from django.conf import settings
from temporalio.client import Client


class TemporalClient:
    TASK_QUEUE = settings.TEMPORAL_TASK_QUEUE

    @classmethod
    async def connect(cls):
        return await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)

    # This sends the workflow name, doc id, delay is added, and queue name
    @classmethod
    async def start_async(cls, workflow_run, args, workflow_id):
        client = await cls.connect()
        handle = await client.start_workflow(workflow_run, args=args, id=workflow_id, task_queue=cls.TASK_QUEUE)
        return handle.first_execution_run_id

    @classmethod
    def send(cls, workflow_run, args, workflow_id):
        return async_to_sync(cls.start_async)(workflow_run, args, workflow_id)

    @classmethod
    async def cancel_async(cls, workflow_id, run_id):
        client = await cls.connect()
        await client.get_workflow_handle(workflow_id, run_id=run_id).cancel()

    @classmethod
    def cancel(cls, workflow_id, run_id):
        async_to_sync(cls.cancel_async)(workflow_id, run_id)

    # Whatch is used to get currentl state of workflow
    @classmethod
    async def watch(cls, workflow_id, run_id):
        client = await cls.connect()
        handle = client.get_workflow_handle(workflow_id, run_id=run_id)
        history = await handle.fetch_history()
        yield history.events
        seen = history.events[-1].event_id if history.events else 0
        async for event in handle.fetch_history_events(wait_new_event=True):
            if event.event_id > seen:
                yield [event]
