from django.urls import path
from . import views

urlpatterns = [
    path("graph/", views.AgentGraphView.as_view(), name="agent_graph"),
    path("graph/save", views.AgentGraphSaveView.as_view(), name="agent_graph_save"),
]
