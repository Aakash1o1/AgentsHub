from django.shortcuts import render, redirect
from chat.models import Chat
from scraper.models import Document
from chat.services.chat import ChatService
from analysis.services.datasets import DatasetService
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
            "user": user,
            "vendors": user.vendors.all(),
            "vendor": user.active_vendor,
            "chats": chats,
            "open_chat": open_chat,
            "chat_messages": open_chat.messages.visible() if open_chat else [],
            "document_types": Document.SOURCE_CHOICES,
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


class SendMessageView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        chat_id = request.POST.get("chat_id")
        question = request.POST.get("question")
        chat = Chat.objects.visible_to(user).filter(id=chat_id).first() if user.active_vendor else None
        token = request.POST.get("file") or ""
        file_path = DatasetService.path_from_token(token, chat, user) if chat and token else ""
        if chat and question:
            ChatService().ask(chat, question, user, file_path)
        if chat:
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

