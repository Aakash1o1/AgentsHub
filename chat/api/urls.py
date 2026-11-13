from django.urls import path, re_path
from . import views

urlpatterns = [
    path("", views.ChatHomeView.as_view(), name="chat_home"),
    path("chat/create", views.CreateChatView.as_view(), name="create_chat"),
    path("message/send", views.SendMessageView.as_view(), name="send_message"),
    path("chat/link/add", views.AddChatLinkView.as_view(), name="add_chat_link"),
    path("chat/summarize", views.SummarizeView.as_view(), name="summarize"),
    path("tasks", views.ChatTasksView.as_view(), name="chat_tasks"),
    path("chat/file/<int:message_id>/summary", views.StartFileSummaryView.as_view(), name="start_file_summary"),
    path("chat/file/<int:message_id>/knowledge", views.AddFileToKnowledgeView.as_view(), name="add_file_to_knowledge"),
    re_path(r"^workflow/(?P<workflow_id>(?:document|chat-file-summary)-\d+)/(?P<run_id>[0-9a-f-]+)/control$",
            views.WorkflowControlView.as_view(), name="workflow_control"),
]
