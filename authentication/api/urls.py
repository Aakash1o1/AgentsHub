from django.urls import path
from oauth2_provider.urls import base_urlpatterns, oidc_urlpatterns
from . import views

app_name = "oauth2_provider"

urlpatterns = [
    path("authorize/", views.SuperuserAuthorizationView.as_view(), name="authorize"),
    # These are some pre built url patterns needed for OIDC
    *base_urlpatterns,
    *oidc_urlpatterns,
]