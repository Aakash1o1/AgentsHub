from django.urls import path
from . import views

urlpatterns = [
    path("upload", views.UploadChatFileView.as_view(), name="upload_chat_file"),
]
