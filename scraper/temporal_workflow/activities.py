import requests
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import close_old_connections
from django.utils import timezone
from pypdf.errors import PyPdfError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from scraper.models import Chunk, Document
from scraper.services.ingestion import ScraperService


class DocumentActivities:
    TEXT_PATH = "extracted/{}.txt"

    def __init__(self):
        self.scraper = ScraperService()

    @activity.defn
    def mark_stage(self, doc_id, stage):
        close_old_connections()
        Document.objects.filter(id=doc_id).update(status=stage, error="", updated_at=timezone.now())

    @activity.defn
    def extract_text(self, doc_id):
        close_old_connections()
        doc = Document.objects.filter(id=doc_id, is_active=True).first()
        if doc is None:
            raise ApplicationError(f"Document {doc_id} not found or deleted", non_retryable=True)

        try:
            text = ScraperService.read_source(doc.as_message())
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code is not None and 400 <= code < 500:
                raise ApplicationError(f"HTTP {code} for {doc.url}", non_retryable=True) from e
            raise
        except PyPdfError as e:
            raise ApplicationError(f"Unreadable PDF: {e}", non_retryable=True) from e

        path = self.TEXT_PATH.format(doc_id)
        default_storage.delete(path)
        default_storage.save(path, ContentFile(text.encode("utf-8")))

        Chunk.objects.filter(parent_doc_id=doc_id).delete()
        total = len(self.scraper.chunk_text(text))
        Document.objects.filter(id=doc_id).update(total_chunks=total, updated_at=timezone.now())
        return total

    @activity.defn
    def embed_batch(self, doc_id, start, end):
        close_old_connections()
        with default_storage.open(self.TEXT_PATH.format(doc_id), "rb") as fh:
            text = fh.read().decode("utf-8")

        pieces = self.scraper.chunk_text(text)[start:end]
        chunks = [
            Chunk(
                parent_doc_id=doc_id,
                chunk_num=start + i,
                content=piece,
                embedding=self.scraper.ollama.embed(piece),
            )
            for i, piece in enumerate(pieces)
        ]
        Chunk.objects.bulk_create(
            chunks,
            update_conflicts=True,
            unique_fields=["parent_doc", "chunk_num"],
            update_fields=["content", "embedding", "updated_at"],
        )
        return len(chunks)

    @activity.defn
    def finish(self, doc_id, status, error=""):
        close_old_connections()
        ScraperService.finish(doc_id, status, error)

    @activity.defn
    def announce(self, doc_id, status, error=""):
        close_old_connections()
        doc = Document.objects.filter(id=doc_id).first()
        if doc is not None:
            ScraperService.announce(doc.as_message(), status, error)
