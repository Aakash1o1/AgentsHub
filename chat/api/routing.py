from django.urls import path, re_path

from chat.api.consumers import ChatConsumer, ChatFileSummaryProgressConsumer, ChatFileWorkflowProgressConsumer

websocket_urlpatterns = [
    path("ws/chat/<int:chat_id>/", ChatConsumer.as_asgi()),
    path("ws/chat/file/<int:message_id>/summary/<str:run_id>/", ChatFileSummaryProgressConsumer.as_asgi()),
    re_path(r"^ws/chat/workflow/(?P<workflow_id>chat-file-summary-\d+)/(?P<run_id>[0-9a-f-]+)/summary/$",
            ChatFileWorkflowProgressConsumer.as_asgi()),
]
