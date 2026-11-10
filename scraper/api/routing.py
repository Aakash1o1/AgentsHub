from django.urls import path, re_path

from scraper.api.consumers import DocumentProgressConsumer, WorkflowProgressConsumer

websocket_urlpatterns = [
    path("ws/scraper/document/<int:doc_id>/progress/", DocumentProgressConsumer.as_asgi()),
    re_path(r"^ws/scraper/workflow/(?P<workflow_id>document-\d+)/(?P<run_id>[0-9a-f-]+)/progress/$",
            WorkflowProgressConsumer.as_asgi()),
]
