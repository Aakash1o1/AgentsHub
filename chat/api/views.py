from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import JsonResponse
from chat.models import Chat, Message
from scraper.models import Document
from chat.services.access import TaskAccess
from chat.services.chat import ChatService
from chat.services.files import ChatFileService
from chat.services.jobs import ChatJobs
from chat.services.notifier import ChatNotifier
from chat.temporal_workflow.temporal import ChatFileSummaries
from base.services.temporal import PauseRefused, TemporalClient
from scraper.api.views import VisibleDocumentMixin
from scraper.services.progress import DocumentProgress
from scraper.temporal_workflow.temporal import DocumentWorkflows
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError
from django.contrib import admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import View


# Create your views here
class ChatHomeView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        vendor = user.active_vendor
        chats = self.recently_used(Chat.objects.visible_to(user)) if vendor else []
        chat_id = request.GET.get("chat")
        open_chat = None
        if chat_id and vendor:
            open_chat = Chat.objects.visible_to(user).filter(id=chat_id).first()# Without first, it will return a container and for foretign key checks, we need an object
        context = admin.site.each_context(request)
        context.update({
            "is_fullwidth": "1",
            "title": "Chat",
            "user": user,
            "vendors": user.vendors.all(),
            "vendor": user.active_vendor,
            "chats": chats,
            "open_chat": open_chat,
            "chat_messages": open_chat.messages.visible() if open_chat else [],
            "can_see_tasks": TaskAccess.allowed(user),
            "agents": vendor.agents.filter(is_active=True).order_by("-is_default", "label") if vendor else [],
        })
        return render(request, "chat_admin.html", context)

    @staticmethod
    def recently_used(chats):
        return chats.order_by("-last_message_at", "-id")


class CreateChatView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        if user.active_vendor:
            chat = Chat.objects.create(vendor=user.active_vendor, title=Chat.DEFAULT_TITLE, user=user, created_by=user, updated_by=user)
            return redirect(f"/?chat={chat.id}")
        return redirect("chat_home")


class SummarizeView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        chat_id = request.POST.get("chat_id")
        chat = Chat.objects.visible_to(user).filter(id=chat_id).first() if user.active_vendor else None
        if chat:
            ChatService().summarize_chat(chat, user)
            return redirect(f"/?chat={chat.id}")
        return redirect("chat_home")


class AddChatLinkView(LoginRequiredMixin, View):
    REPLY = "Link saved to this chat. Ask a question about it, or ask me to add it to the knowledge base."

    @staticmethod
    def error(text):
        return JsonResponse({"level": "error", "message": text}, status=400)

    def post(self, request):
        user = request.user
        url = request.POST.get("url", "").strip()
        source_type = request.POST.get("source_type") or ChatFileService.link_type(url)
        chat = Chat.objects.visible_to(user).filter(id=request.POST.get("chat_id") or None).first() if user.active_vendor else None
        if chat is None:
            return self.error("Open a chat first.")
        if source_type not in dict(Document.SOURCE_CHOICES):
            return self.error("Unknown link type.")
        try:
            URLValidator(schemes=["http", "https"])(url)
        except ValidationError:
            return self.error("Enter a full http(s) link.")

        service = ChatService()
        renamed = service.title_from_first_message(chat, url, user)
        link = ChatFileService.save_link(chat, url, source_type, user)
        reply = Message.objects.create(chat=chat, role="assistant", message=self.REPLY,
                                       chat_session_key=chat.session_key, user=user, created_by=user, updated_by=user)
        for message in (link, reply):
            ChatNotifier.notify_chat(chat.id, {"event": "message", "message": service.serialize_message(message)})
        if renamed:
            ChatNotifier.notify_chat(chat.id, {"event": "renamed", "chat_id": chat.id, "title": chat.title})
        return JsonResponse({"level": "success", "id": link.id, "message": self.REPLY})


class ChatFileActionView(LoginRequiredMixin, View):
    @staticmethod
    def reply(level, text, status=200, **extra):
        return JsonResponse({"level": level, "message": text, **extra}, status=status)

    @staticmethod
    def visible_file(user, message_id):
        if not user.active_vendor:
            return None
        message = Message.objects.visible().filter(id=message_id, chat__in=Chat.objects.visible_to(user)).first()
        if message is None or not message.has_source or message.is_dataset:
            return None
        return message

    def post(self, request, message_id):
        message = self.visible_file(request.user, message_id)
        if message is None:
            return self.reply("error", "File not found in your chats.", status=404)
        try:
            return self.act(request, message)
        except Exception as error:
            return self.reply("error", f"Could not start: {error}", status=400)


class StartFileSummaryView(ChatFileActionView):
    def act(self, request, message):
        try:
            run_id = ChatFileSummaries.start(message)
        except WorkflowAlreadyStartedError:
            return self.reply("warning", f"{message.file_label} is already summarised or being summarised.")
        return self.reply("success", f"Summary of {message.file_label} started.",
                          progress_url=ChatFileSummaries.socket_path(message, run_id))


class AddFileToKnowledgeView(ChatFileActionView):
    def act(self, request, message):
        doc, created = ChatFileService.add_to_knowledge_base(message, message.chat.vendor, request.user)
        if not created:
            return self.reply("warning", f"{message.file_label} is already in the knowledge base as document {doc.id}.")
        ChatFileService.start_processing(doc, request.user)
        return self.reply("success", f"{message.file_label} added to the knowledge base as document {doc.id}.",
                          progress_url=DocumentProgress.socket_path(doc.id))


class ChatTasksView(LoginRequiredMixin, View):
    def get(self, request):
        if not TaskAccess.allowed(request.user):
            return JsonResponse({"error": TaskAccess.DENIED}, status=403)
        if not request.user.active_vendor:
            return JsonResponse({"error": "Pick a vendor first."}, status=404)
        try:
            chat = Chat.objects.visible_to(request.user).filter(id=request.GET.get("chat") or None).first()
            return JsonResponse({"tasks": ChatJobs.tasks(request.user, chat)})
        except Exception as error:
            return JsonResponse({"error": f"Could not read the tasks from Temporal: {error}"}, status=502)


class WorkflowControlView(LoginRequiredMixin, VisibleDocumentMixin, View):
    ACTIONS = {"pause": TemporalClient.pause, "resume": TemporalClient.resume, "cancel": TemporalClient.cancel}
    REASONS = {"pause": "Paused", "resume": "Resumed", "cancel": "Canceled"}

    def visible(self, user, workflow_id):
        if workflow_id.startswith(DocumentWorkflows.WORKFLOW_PREFIX):
            return self.visible_document(user, DocumentWorkflows.doc_id(workflow_id)) is not None
        return ChatFileActionView.visible_file(user, ChatFileSummaries.message_id(workflow_id)) is not None

    def post(self, request, workflow_id, run_id):
        name = request.POST.get("action")
        action = self.ACTIONS.get(name)
        if not TaskAccess.allowed(request.user):
            return JsonResponse({"error": TaskAccess.DENIED}, status=403)
        if action is None:
            return JsonResponse({"error": "Unknown action."}, status=400)
        if not self.visible(request.user, workflow_id):
            return JsonResponse({"error": "Workflow not found."}, status=404)
        try:
            action(workflow_id, run_id, f"{self.REASONS[name]} by {request.user.get_username()} in the app")
        except PauseRefused as error:
            return JsonResponse({"error": f"Could not pause: {error}"}, status=409)
        except RPCError as error:
            return JsonResponse({"error": f"Temporal refused: {error}"}, status=409)
        return JsonResponse({"ok": True})
