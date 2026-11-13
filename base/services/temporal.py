import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from django.conf import settings
from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.enums.v1 import PendingWorkflowTaskState, WorkflowExecutionStatus
from temporalio.api.workflowservice.v1 import (
    DescribeWorkflowExecutionRequest,
    ListWorkflowExecutionsRequest,
    PauseWorkflowExecutionRequest,
    UnpauseWorkflowExecutionRequest,
)
from temporalio.client import Client
from temporalio.common import SearchAttributeKey, SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy

from base.services.keycloak import KeycloakToken

logger = logging.getLogger(__name__)


class PauseRefused(Exception):
    pass


class TemporalClient:
    TASK_QUEUE = settings.TEMPORAL_TASK_QUEUE
    TOKEN = KeycloakToken.for_django()
    TOKEN_CHECK_SECONDS = 30
    REPOLL_SECONDS = 2
    IDENTITY = "rag-app"
    PAUSE_RETRY_SECONDS = 0.025
    PAUSE_GUARD_SECONDS = 2
    WORKER_DOWN_SECONDS = 5

    @classmethod
    async def connect(cls, token=None):
        token = token or cls.TOKEN
        return await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE,
                                    rpc_metadata=await token.header())

    @classmethod
    async def keep_token_fresh(cls, client, token=None):
        token = token or cls.TOKEN
        while True:
            await asyncio.sleep(cls.TOKEN_CHECK_SECONDS)
            client.rpc_metadata = await token.header()

    # This sends the workflow name, doc id, delay is added, and queue name
    @classmethod
    async def start_async(cls, workflow_run, args, workflow_id, labels=None, memo=None, reuse=None):
        client = await cls.connect()
        handle = await client.start_workflow(workflow_run, args=args, id=workflow_id, task_queue=cls.TASK_QUEUE,
                                             search_attributes=labels, memo=memo,
                                             id_reuse_policy=reuse or WorkflowIDReusePolicy.ALLOW_DUPLICATE)
        return handle.first_execution_run_id

    @classmethod
    def send(cls, workflow_run, args, workflow_id, labels=None, memo=None, reuse=None):
        return async_to_sync(cls.start_async)(workflow_run, args, workflow_id, labels, memo, reuse)

    @classmethod
    async def describe_async(cls, client, workflow_id, run_id):
        return await client.workflow_service.describe_workflow_execution(DescribeWorkflowExecutionRequest(
            namespace=settings.TEMPORAL_NAMESPACE, execution=WorkflowExecution(workflow_id=workflow_id, run_id=run_id)))

    @classmethod
    def request(cls, request_class, workflow_id, run_id, reason):
        return request_class(namespace=settings.TEMPORAL_NAMESPACE, workflow_id=workflow_id, run_id=run_id,
                             identity=cls.IDENTITY, reason=reason, request_id=str(uuid.uuid4()))

    @classmethod
    def safe_to_pause(cls, description):
        status = description.workflow_execution_info.status
        if status == WorkflowRun.PAUSED:
            raise PauseRefused("It is already paused.")
        if status != WorkflowRun.RUNNING:
            raise PauseRefused("It is not running.")
        task = description.pending_workflow_task
        if not description.HasField("pending_workflow_task") or task.state != WorkflowRun.TASK_WAITING:
            return True
        waited = datetime.now(timezone.utc) - task.original_scheduled_time.ToDatetime(tzinfo=timezone.utc)
        if waited.total_seconds() > cls.WORKER_DOWN_SECONDS:
            raise PauseRefused("The Temporal worker is not picking up work, so it cannot be paused safely now. "
                               "Try again when the worker is running.")
        return False

    @classmethod
    async def pause_async(cls, workflow_id, run_id, reason):
        client = await cls.connect()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + cls.PAUSE_GUARD_SECONDS
        checks = 1
        while not cls.safe_to_pause(await cls.describe_async(client, workflow_id, run_id)):
            if loop.time() > deadline:
                raise PauseRefused("It is busy between two steps. Try again in a moment.")
            await asyncio.sleep(cls.PAUSE_RETRY_SECONDS)
            checks += 1
        await client.workflow_service.pause_workflow_execution(
            cls.request(PauseWorkflowExecutionRequest, workflow_id, run_id, reason))
        logger.info("Paused %s after %d check(s)", workflow_id, checks)
        return checks

    @classmethod
    def pause(cls, workflow_id, run_id, reason="Paused from the app"):
        return async_to_sync(cls.pause_async)(workflow_id, run_id, reason)

    @classmethod
    async def resume_async(cls, workflow_id, run_id, reason):
        client = await cls.connect()
        await client.workflow_service.unpause_workflow_execution(
            cls.request(UnpauseWorkflowExecutionRequest, workflow_id, run_id, reason))

    @classmethod
    def resume(cls, workflow_id, run_id, reason="Resumed from the app"):
        async_to_sync(cls.resume_async)(workflow_id, run_id, reason)

    @classmethod
    async def cancel_async(cls, workflow_id, run_id, reason):
        client = await cls.connect()
        await client.get_workflow_handle(workflow_id, run_id=run_id).cancel()
        description = await cls.describe_async(client, workflow_id, run_id)
        if description.workflow_execution_info.status == WorkflowRun.PAUSED:
            await client.workflow_service.unpause_workflow_execution(
                cls.request(UnpauseWorkflowExecutionRequest, workflow_id, run_id, reason))

    @classmethod
    def cancel(cls, workflow_id, run_id, reason="Canceled from the app"):
        async_to_sync(cls.cancel_async)(workflow_id, run_id, reason)

    @classmethod
    async def list_async(cls, query):
        client = await cls.connect()
        runs, token = [], b""
        while True:
            reply = await client.workflow_service.list_workflow_executions(ListWorkflowExecutionsRequest(
                namespace=settings.TEMPORAL_NAMESPACE, query=query, next_page_token=token))
            runs += [WorkflowRun(info) for info in reply.executions]
            token = reply.next_page_token
            if not token:
                return runs

    @classmethod
    def list(cls, query):
        return async_to_sync(cls.list_async)(query)

    # Whatch is used to get currentl state of workflow
    @classmethod
    async def watch(cls, workflow_id, run_id):
        client = await cls.connect()
        refresher = asyncio.create_task(cls.keep_token_fresh(client))
        try:
            handle = client.get_workflow_handle(workflow_id, run_id=run_id)
            history = await handle.fetch_history()
            yield history.events
            seen = history.events[-1].event_id if history.events else 0
            while True:
                fresh = False
                async for event in handle.fetch_history_events(wait_new_event=True):
                    if event.event_id > seen:
                        seen = event.event_id
                        fresh = True
                        yield [event]
                if not fresh:
                    await asyncio.sleep(cls.REPOLL_SECONDS)
        finally:
            refresher.cancel()


class WorkflowRun:
    RUNNING = WorkflowExecutionStatus.WORKFLOW_EXECUTION_STATUS_RUNNING
    COMPLETED = WorkflowExecutionStatus.WORKFLOW_EXECUTION_STATUS_COMPLETED
    PAUSED = WorkflowExecutionStatus.WORKFLOW_EXECUTION_STATUS_PAUSED
    ACTIVE = (RUNNING, PAUSED)
    TASK_WAITING = PendingWorkflowTaskState.PENDING_WORKFLOW_TASK_STATE_SCHEDULED

    def __init__(self, info):
        self.id = info.execution.workflow_id
        self.run_id = info.execution.run_id
        self.workflow_type = info.type.name
        self.status = info.status
        self.start_time = info.start_time.ToDatetime(tzinfo=timezone.utc)
        self.close_time = info.close_time.ToDatetime(tzinfo=timezone.utc) if info.HasField("close_time") else None
        self.memo = {key: json.loads(payload.data) for key, payload in info.memo.fields.items()}

    @property
    def status_name(self):
        return WorkflowExecutionStatus.Name(self.status).removeprefix("WORKFLOW_EXECUTION_STATUS_").lower()


class JobLabels:
    CHAT = SearchAttributeKey.for_keyword("ChatId")
    VENDOR = SearchAttributeKey.for_keyword("VendorId")

    @classmethod
    def build(cls, chat=None, vendor_id=None):
        pairs = []
        if chat is not None:
            pairs.append(SearchAttributePair(cls.CHAT, str(chat.id)))
        if vendor_id is not None:
            pairs.append(SearchAttributePair(cls.VENDOR, str(vendor_id)))
        return TypedSearchAttributes(pairs)

    @classmethod
    def for_chat_file(cls, message):
        return cls.build(chat=message.chat, vendor_id=message.chat.vendor_id if message.chat else None)

    @staticmethod
    def memo(message):
        return {"file": message.file_label, "file_id": message.id}

    @staticmethod
    def vendor_query(vendor_id):
        return f"VendorId = '{vendor_id}'"

    @classmethod
    def chat_query(cls, chat):
        return f"ChatId = '{chat.id}' AND {cls.vendor_query(chat.vendor_id)}"
