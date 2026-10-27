from django.urls import path
from . import views

urlpatterns = [
    path("", views.ChatHomeView.as_view(), name="chat_home"),
    path("chat/create", views.CreateChatView.as_view(), name="create_chat"),
    path("message/send", views.SendMessageView.as_view(), name="send_message"),
    path("chat/summarize", views.SummarizeView.as_view(), name="summarize"),
]
