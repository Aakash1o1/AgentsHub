from django.views import View
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from temporalio.service import RPCError
from temporalio.exceptions import WorkflowAlreadyStartedError
from scraper.models import Document
from scraper.services.queue import DocumentQueue
from scraper.temporal_workflow.temporal import DocumentWorkflows
from scraper.tasks import DocumentTasks
from chat.models import Chat, Message
from chat.services.chat import ChatService
from chat.services.notifier import ChatNotifier
from agent.services.tools import DocumentTools


class AddDocumentView(LoginRequiredMixin, View):
    @staticmethod
    def error(text):
        return JsonResponse({"level": "error", "message": text}, status=400)

    def post(self, request):
        user = request.user
        url = request.POST.get("url", "").strip()
        source_type = request.POST.get("source_type", "")
        if user.active_vendor is None:
            return self.error("Pick a vendor first.")
        if source_type not in dict(Document.SOURCE_CHOICES):
            return self.error("Pick a document type.")
        
        try:
            URLValidator(schemes=["http", "https"])(url)
        except ValidationError:
            return self.error("Enter a full http(s) link.")
        chat = Chat.objects.visible_to(user).filter(id=request.POST.get("chat_id") or None).first()
        
        # Make row in document
        doc = Document.objects.create(vendor=user.active_vendor, url=url, source_type=source_type, created_by=user, updated_by=user)
        try:
        # Start temporal workflow
            workflow_id = DocumentWorkflows.start(doc, user=user)
            level, text = "success", f"Document {doc.id} added. Processing started as {workflow_id}."
        except Exception as exc:
            level, text = "warning", f"Document {doc.id} added, but processing could not start: {exc}"

        if chat:
            service = ChatService()
            question = f"Add {doc.get_source_type_display()} for processing: {url}"
            renamed = service.title_from_first_message(chat, question, user)
            doc.refresh_from_db()
            saved = [
                service.save_user_message(chat, question, user),
                Message.objects.create(chat=chat, role="assistant", message=text,
                                       artifact=DocumentTools.card("Added document", [doc]),
                                       chat_session_key=chat.session_key, user=user, created_by=user, updated_by=user),
            ]
            for message in saved:
                ChatNotifier.notify_chat(chat.id, {"event": "message", "message": service.serialize_message(message)})
            if renamed:
                ChatNotifier.notify_chat(chat.id, {"event": "renamed", "chat_id": chat.id, "title": chat.title})
        return JsonResponse({"level": level, "id": doc.id, "message": text})

class VisibleDocumentMixin:
    def visible_document(self, user, doc_id):
        vendor = user.active_vendor
        if user.is_superuser and vendor is None:
            return Document.objects.filter(id=doc_id).first()
        if vendor is None:
            return None
        return Document.objects.filter(id=doc_id, vendor=vendor).first()


# Pushes document to kafka queue using base functions we made in services
class EnqueueDocumentView(LoginRequiredMixin, VisibleDocumentMixin, View):
    MODES = ("process", "process_now", "schedule", "process_temporal", "schedule_temporal")

    def reply(self, request, level, text):
        if request.headers.get("Accept", "").startswith("application/json"):
            return JsonResponse({"level": level, "message": text}, status=400 if level == "error" else 200)
        getattr(messages, level)(request, text)
        return redirect(request.META.get("HTTP_REFERER") or "admin:scraper_document_changelist")

    def post(self, request, doc_id):
        mode = request.POST.get("mode")
        if mode not in self.MODES:
            return self.reply(request, "error", "Unknown action.")

        doc = self.visible_document(request.user, doc_id)
        if doc is None:
            return self.reply(request, "error", "Document not found for the active vendor.")

        user = request.user
        try:
            if mode == "schedule":
                delay = DocumentTasks.schedule(doc, user=user)
                level, text = "success", f"Document {doc.id} scheduled in {delay}s."
            elif mode in ("process_temporal", "schedule_temporal"):
                delay = settings.DOCUMENT_SCHEDULE_DELAY_SECONDS if mode == "schedule_temporal" else 0
                workflow_id = DocumentWorkflows.start(doc, delay_seconds=delay, user=user)
                level, text = "success", f"Document {doc.id} started as Temporal workflow {workflow_id}."
            else:
                priority = mode == "process_now"
                DocumentQueue.publish(doc, priority=priority, user=user)
                lane = "priority queue" if priority else "queue"
                level, text = "success", f"Document {doc.id} sent to the {lane}."
        except WorkflowAlreadyStartedError:
            level, text = "warning", f"Document {doc.id} is already being processed by Temporal."
        except Exception as exc:
            level, text = "error", f"Could not queue document {doc.id}: {exc}"
        return self.reply(request, level, text)


class CancelDocumentView(LoginRequiredMixin, VisibleDocumentMixin, View):
    def post(self, request, doc_id):
        doc = self.visible_document(request.user, doc_id)
        if doc is None or not doc.workflow_run_id:
            return JsonResponse({"error": "No Temporal run for this document."}, status=404)
        try:
            DocumentWorkflows.stop(doc)
        except RPCError as exc:
            return JsonResponse({"error": f"Could not cancel: {exc}"}, status=409)
        return JsonResponse({"ok": True})
