import asyncio

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from scraper.api.views import VisibleDocumentMixin
from scraper.services.progress import DocumentProgress


class DocumentProgressConsumer(VisibleDocumentMixin, AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.task = None
        user = self.scope["user"]
        doc_id = self.scope["url_route"]["kwargs"]["doc_id"]
        doc = await database_sync_to_async(self.visible_document)(user, doc_id) if user.is_authenticated else None
        if doc is None or not doc.workflow_run_id:
            await self.close()
            return
        await self.accept()
        self.task = asyncio.create_task(self.stream(doc))

    async def disconnect(self, code):
        if self.task is not None:
            self.task.cancel()

    async def stream(self, doc):
        try:
            async for snapshot in DocumentProgress(doc).stream():
                await self.send_json(snapshot)
        except Exception as exc:
            await self.send_json({"error": f"Could not read the Temporal run: {exc}"})
        await self.close()
