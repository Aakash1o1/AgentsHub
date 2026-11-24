from django.urls import path
from . import views

urlpatterns = [
    path("graph/", views.AgentGraphView.as_view(), name="agent_graph"),
    path("graph/save", views.AgentGraphSaveView.as_view(), name="agent_graph_save"),
    path("graph/prompts", views.AgentPromptsView.as_view(), name="agent_graph_prompts"),
    path("<slug:slug>/message", views.AgentMessageView.as_view(), name="agent_message"),
]
