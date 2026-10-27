from django.urls import path
from . import views

urlpatterns = [
    path("upload", views.UploadDatasetView.as_view(), name="upload_dataset"),
]
