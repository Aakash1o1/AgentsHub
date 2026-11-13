from django.urls import path
from . import views

urlpatterns = [
    path("scraper/document/<int:doc_id>/enqueue", views.EnqueueDocumentView.as_view(), name="enqueue_document"),
]
