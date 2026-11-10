from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect
from temporalio.service import RPCError
from temporalio.exceptions import WorkflowAlreadyStartedError
from scraper.models import Document
from scraper.services.queue import DocumentQueue
from scraper.temporal_workflow.temporal import DocumentWorkflows
from scraper.tasks import DocumentTasks


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
    MODES = ("process", "process_now", "schedule", "process_temporal")

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
            elif mode == "process_temporal":
                workflow_id = DocumentWorkflows.start(doc, user=user)
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
