from django.urls import path

from scraper.api.consumers import DocumentProgressConsumer

websocket_urlpatterns = [
    path("ws/scraper/document/<int:doc_id>/progress/", DocumentProgressConsumer.as_asgi()),
]
