import json
from datetime import timedelta
from pathlib import Path
from django.db import models, transaction
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.text import slugify
from base.models import BaseModel
from vendor.models import Vendor
from base.utils import generate_ulid
from scraper.models import Document


class ChatFile:
    FOLDER = "chat_files"

    @staticmethod
    def upload_to(instance, filename):
        return f"{ChatFile.FOLDER}/{generate_ulid()}/{default_storage.get_valid_name(filename)}"


# Single source of truth for "which chats a user may see"
class ChatQuerySet(models.QuerySet):
    def visible_to(self, user):
       return self.filter(user=user, vendor=user.active_vendor, is_active=True)


class MessageQuerySet(models.QuerySet):
    def visible(self):
        return self.filter(is_active=True)


# Create your models here.
class Chat(BaseModel):
    DEFAULT_TITLE = "Untitled"
    ANSWER_LOCK_SECONDS = 300

    title = models.CharField(max_length=50)
    vendor = models.ForeignKey(Vendor,on_delete=models.SET_NULL,null=True,blank=True, related_name="chats")
    session_key = models.CharField(max_length=26, unique=True, default=generate_ulid, editable=False)
    summary = models.TextField(blank=True, default="")
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True, blank=True,related_name="chats",)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    answering_since = models.DateTimeField(null=True, blank=True, editable=False)

    objects = models.Manager.from_queryset(ChatQuerySet)()

    class Meta:
        permissions = [("view_temporal_tasks", "Can see Temporal tasks")]

    def __str__(self):
        return self.title

    @classmethod
    def answer_lock_cutoff(cls):
        return timezone.now() - timedelta(seconds=cls.ANSWER_LOCK_SECONDS)

    @property
    def is_answering(self):
        return self.answering_since is not None and self.answering_since > self.answer_lock_cutoff()



class Message(BaseModel):
    ROLE_TYPE = [
        ("user","User"),
        ("assistant", "Assistant"),
    ]
    ARTIFACT_MARKER = "<!--artifact-->"
    DATASET_EXTENSIONS = (".csv", ".xlsx")

    role = models.CharField(choices=ROLE_TYPE,max_length=20)
    message = models.TextField()
    attachment = models.FileField(upload_to=ChatFile.upload_to, blank=True, max_length=255)
    chat = models.ForeignKey(Chat,on_delete=models.SET_NULL,null=True,blank=True,related_name="messages")
    chat_session_key = models.CharField(max_length=26, blank=True, default="")
    agent = models.ForeignKey("agent.Agent",on_delete=models.SET_NULL,null=True,blank=True,related_name="messages",)
    url = models.URLField(blank=True)
    source_type = models.CharField(choices=Document.SOURCE_CHOICES, max_length=20, blank=True)
    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_messages")

    objects = models.Manager.from_queryset(MessageQuerySet)()

    class Meta:
        # Without this the DB returns rows in physical order, not chronological.
        ordering = ["created_at", "id"]
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True, blank=True,related_name="messages",)

    @property
    def message_types(self):
        types = []
        if self.text:
            types.append("text")
        if self.attachment:
            types.append(self.extension.lstrip("."))
        if self.url:
            types.append("link")
        return types

    @classmethod
    def join_content(cls, text, artifact=None):
        text = text.replace(cls.ARTIFACT_MARKER, "")
        if not artifact:
            return text
        return f"{text}\n{cls.ARTIFACT_MARKER}{json.dumps(artifact)}"

    @classmethod
    def split_content(cls, raw):
        text, marker, tail = raw.rpartition(cls.ARTIFACT_MARKER)
        if not marker:
            return raw, None
        try:
            artifact = json.loads(tail)
        except ValueError:
            return raw, None
        if not isinstance(artifact, dict):
            return raw, None
        return text.removesuffix("\n"), artifact

    @property
    def text(self):
        if self.role != "assistant":
            return self.message
        return self.split_content(self.message)[0]

    @property
    def artifact(self):
        if self.role != "assistant":
            return None
        return self.split_content(self.message)[1]

    @property
    def has_source(self):
        return bool(self.attachment or self.url)

    @property
    def extension(self):
        return Path(self.attachment.name).suffix.lower() if self.attachment else ""

    @property
    def is_dataset(self):
        return self.extension in self.DATASET_EXTENSIONS

    @property
    def reading_type(self):
        if self.url:
            return self.source_type or "website"
        return "pdf" if self.extension == ".pdf" else "text"

    @property
    def file_label(self):
        if self.attachment:
            return Path(self.attachment.name).name
        return self.url

    @property
    def table_name(self):
        table = slugify(Path(self.attachment.name).stem).replace("-", "_") or "table"
        if table[0].isdigit():
            table = f"t_{table}"
        return f"{table}_{self.id}"

    def save(self, *args, **kwargs):
        adding = self._state.adding
        with transaction.atomic():
            super().save(*args, **kwargs)
            if adding and self.chat_id:
                Chat.objects.filter(pk=self.chat_id).update(last_message_at=timezone.now())