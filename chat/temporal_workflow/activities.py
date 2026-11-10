import math

import requests
from django.db import close_old_connections
from django.utils import timezone
from pypdf.errors import PyPdfError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from chat.models import Message
from chat.services.chat import ChatService
from chat.services.files import ChatFileService
from chat.services.notifier import ChatNotifier
from scraper.services.client import DeepseekClient


class ChatFileSummaryActivities:
    PIECE_CHARS = 30000
    PAGE_CHARS = 3000
    SHORT_DOC_PAGES = 10

    def __init__(self):
        self.deepseek = DeepseekClient()

    @staticmethod
    def load(message_id):
        message = Message.objects.visible().filter(id=message_id).first()
        if message is None or not message.has_source:
            raise ApplicationError(f"Chat file {message_id} not found or deleted", non_retryable=True)
        return message

    @classmethod
    def text_of(cls, message):
        try:
            return ChatFileService.read_text(message)
        except requests.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code is not None and 400 <= code < 500:
                raise ApplicationError(f"HTTP {code} for {message.url}", non_retryable=True) from e
            raise
        except PyPdfError as e:
            raise ApplicationError(f"Unreadable PDF: {e}", non_retryable=True) from e

    @activity.defn
    def read_text(self, message_id):
        close_old_connections()
        text = self.text_of(self.load(message_id))
        if not text.strip():
            raise ApplicationError("The file has no readable text", non_retryable=True)
        pages = math.ceil(len(text) / self.PAGE_CHARS)
        return {
            "pieces": math.ceil(len(text) / self.PIECE_CHARS),
            "paragraphs": 3 if pages <= self.SHORT_DOC_PAGES else 4,
        }

    @activity.defn
    def summarize_piece(self, message_id, index, total):
        close_old_connections()
        message = self.load(message_id)
        text = self.text_of(message)
        piece = text[index * self.PIECE_CHARS:(index + 1) * self.PIECE_CHARS]
        prompt = (
            f"Below is part {index + 1} of {total} of the document \"{message.file_label}\". "
            "Write short notes of its main points, facts and numbers. Reply with the notes only.\n\n"
            f"{piece}"
        )
        return self.deepseek.ask_deepseek(prompt)

    @activity.defn
    def combine(self, message_id, notes, paragraphs):
        close_old_connections()
        message = self.load(message_id)
        parts = "\n\n".join(f"Notes on part {i + 1}:\n{note}" for i, note in enumerate(notes))
        prompt = (
            f"These are notes on the parts of the document \"{message.file_label}\", in order. "
            f"Write a summary of the whole document in exactly {paragraphs} paragraphs of plain text. "
            "Start the first paragraph with \"This doc is about\". Reply with the summary only.\n\n"
            f"{parts}"
        )
        return self.deepseek.ask_deepseek(prompt)

    @activity.defn
    def save_summary(self, message_id, summary):
        close_old_connections()
        Message.objects.filter(id=message_id).update(summary=summary, updated_at=timezone.now())

    @activity.defn
    def post_summary(self, message_id, summary):
        close_old_connections()
        message = self.load(message_id)
        chat = message.chat
        if chat is None:
            return
        reply = Message.objects.create(
            chat=chat,
            role="assistant",
            message=f"Summary of {message.file_label}:\n\n{summary}",
            chat_session_key=chat.session_key,
            user=message.user,
            created_by=message.user,
            updated_by=message.user,
        )
        try:
            ChatNotifier.notify_chat(chat.id, {"event": "message", "message": ChatService().serialize_message(reply)})
        except Exception:
            pass
