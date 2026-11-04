from pathlib import Path
from urllib.parse import urlparse

from django.core import signing
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from analysis.services.datasets import DatasetService
from chat.models import Message
from scraper.models import Document
from scraper.services.ingestion import ScraperService
from scraper.temporal_workflow.temporal import DocumentWorkflows


class ChatFileService:
    EXTENSIONS = (".csv", ".xlsx", ".pdf", ".txt")
    MAX_UPLOAD_MB = 20
    TOKEN_SALT = "chat-file"
    TOKEN_MAX_AGE_SECONDS = 24 * 60 * 60
    TEXT_PATH = "chat_extracted/{}.txt"
    MAX_CHARS = 150000

    @classmethod
    def upload_error(cls, upload):
        if upload is None:
            return "Choose a file to upload."
        if Path(upload.name).suffix.lower() not in cls.EXTENSIONS:
            return f"Only {', '.join(cls.EXTENSIONS)} files can be uploaded."
        if upload.size == 0:
            return "The file is empty."
        if upload.size > cls.MAX_UPLOAD_MB * 1024 * 1024:
            return f"The file is larger than {cls.MAX_UPLOAD_MB} MB."
        return ""

    @staticmethod
    def is_readable(path):
        extension = Path(path).suffix.lower()
        if extension in Message.DATASET_EXTENSIONS:
            return DatasetService.is_readable(path)
        try:
            if extension == ".pdf":
                return len(PdfReader(path).pages) > 0
            with open(path, "rb") as fh:
                return bool(fh.read().decode("utf-8").strip())
        except (PyPdfError, UnicodeDecodeError, OSError):
            return False

    @classmethod
    def file_token(cls, path, chat, user):
        return signing.dumps({"path": path, "chat": chat.id, "user": user.id}, salt=cls.TOKEN_SALT)

    @classmethod
    def path_from_token(cls, token, chat, user):
        try:
            data = signing.loads(token, salt=cls.TOKEN_SALT, max_age=cls.TOKEN_MAX_AGE_SECONDS)
        except signing.BadSignature:
            return ""
        path = data.get("path", "")
        if data.get("chat") != chat.id or data.get("user") != user.id or not default_storage.exists(path):
            return ""
        if Message.objects.filter(attachment=path).exists():
            return ""
        return path

    @staticmethod
    def for_chat(chat):
        if chat is None:
            return []
        messages = Message.objects.visible().filter(chat=chat).select_related("document").order_by("id")
        return [message for message in messages if message.has_source]

    @classmethod
    def find(cls, chat, file_id):
        return next((message for message in cls.for_chat(chat) if message.id == file_id), None)

    @staticmethod
    def link_type(url):
        extension = Path(urlparse(url).path).suffix.lower()
        return {".pdf": "pdf", ".txt": "text"}.get(extension, "website")

    @staticmethod
    def save_link(chat, url, source_type, user):
        return Message.objects.create(
            chat=chat,
            role="user",
            message=f"Added {dict(Document.SOURCE_CHOICES)[source_type]} link: {url}",
            url=url,
            source_type=source_type,
            chat_session_key=chat.session_key,
            user=user,
            created_by=user,
            updated_by=user,
        )

    @staticmethod
    def source(message):
        return {
            "source_type": message.reading_type,
            "file_name": message.attachment.name if message.attachment else "",
            "url": message.url,
        }

    @classmethod
    def read_text(cls, message):
        path = cls.TEXT_PATH.format(message.id)
        if default_storage.exists(path):
            with default_storage.open(path, "rb") as fh:
                return fh.read().decode("utf-8")
        text = ScraperService.read_source(cls.source(message))
        default_storage.save(path, ContentFile(text.encode("utf-8")))
        return text

    @staticmethod
    def add_to_knowledge_base(message, vendor, user):
        with transaction.atomic():
            locked = Message.objects.select_for_update().get(id=message.id)
            if locked.document_id:
                return locked.document, False
            doc = Document(vendor=vendor, url=locked.url, source_type=locked.reading_type,
                           created_by=user, updated_by=user)
            if locked.attachment:
                with locked.attachment.open("rb") as fh:
                    doc.file.save(locked.file_label, File(fh), save=False)
            doc.save()
            Message.objects.filter(id=locked.id).update(document=doc, updated_by=user)
        return doc, True

    @staticmethod
    def start_processing(doc, user):
        DocumentWorkflows.start(doc, user=user)
        doc.refresh_from_db()
        return DocumentWorkflows.workflow_id(doc)
