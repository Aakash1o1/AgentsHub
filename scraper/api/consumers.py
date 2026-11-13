import asyncio

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from chat.services.access import TaskAccess
from scraper.api.views import VisibleDocumentMixin
from scraper.services.progress import DocumentProgress


class ProgressStreamMixin:
    async def disconnect(self, code):
        if self.task is not None:
            self.task.cancel()

    async def begin(self, progress):
        if not await database_sync_to_async(TaskAccess.allowed)(self.scope["user"]):
            await self.close()
            return
        await self.accept()
        self.task = asyncio.create_task(self.stream(progress))

    async def stream(self, progress):
        try:
            async for snapshot in progress.stream():
                await self.send_json(snapshot)
        except Exception as exc:
            await self.send_json({"error": f"Could not read the Temporal run: {exc}"})
        await self.close()


class DocumentProgressConsumer(ProgressStreamMixin, VisibleDocumentMixin, AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.task = None
        user = self.scope["user"]
        doc_id = self.scope["url_route"]["kwargs"]["doc_id"]
        doc = await database_sync_to_async(self.visible_document)(user, doc_id) if user.is_authenticated else None
        if doc is None or not doc.workflow_run_id:
            await self.close()
            return
        await self.begin(DocumentProgress.for_document(doc))


class WorkflowProgressConsumer(ProgressStreamMixin, AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.task = None
        if not self.scope["user"].is_authenticated:
            await self.close()
            return
        kwargs = self.scope["url_route"]["kwargs"]
        await self.begin(DocumentProgress.for_workflow(kwargs["workflow_id"], kwargs["run_id"]))
