from django.urls import path
from . import views

urlpatterns = [
    path("scraper/document/add", views.AddDocumentView.as_view(), name="add_document"),
    path("scraper/document/<int:doc_id>/enqueue", views.EnqueueDocumentView.as_view(), name="enqueue_document"),
    path("scraper/document/<int:doc_id>/cancel", views.CancelDocumentView.as_view(), name="cancel_document"),
]
