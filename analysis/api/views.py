from pathlib import Path

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.views import View

from analysis.services.datasets import DatasetService
from chat.models import Chat, ChatFile


class UploadDatasetView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        chat = self.open_chat(user, request.POST.get("chat_id"))
        if chat is None:
            return JsonResponse({"error": "Open a chat before uploading a CSV."}, status=404)
        upload = request.FILES.get("file")
        error = DatasetService.upload_error(upload)
        if error:
            return JsonResponse({"error": error}, status=400)
        path = default_storage.save(ChatFile.upload_to(None, upload.name), upload)
        if not DatasetService.is_readable(default_storage.path(path)):
            default_storage.delete(path)
            return JsonResponse({"error": f"Could not read {upload.name}. Check that the file is a valid CSV."}, status=400)
        return JsonResponse({"name": Path(path).name, "token": DatasetService.file_token(path, chat, user)})

    @staticmethod
    def open_chat(user, chat_id):
        if not user.active_vendor or not chat_id:
            return None
        return Chat.objects.visible_to(user).filter(id=chat_id).first()
