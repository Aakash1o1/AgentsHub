from urllib.parse import urlencode

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.mixins import UserPassesTestMixin
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView
from oauth2_provider.views import AuthorizationView

from authentication.services.backends import KeycloakLogout


# This defines if user dosenot have a token, they will be sent to django login page
# If they are logged in but not super user, they will get 403 error
class SuperuserAuthorizationView(UserPassesTestMixin, AuthorizationView):
    def test_func(self):
        return self.request.user.is_superuser


class KeycloakLoginView(View):
    def get(self, request):
        target = request.GET.get(REDIRECT_FIELD_NAME, "")
        if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
            target = settings.LOGIN_REDIRECT_URL
        return redirect(f"{reverse('oidc_authentication_init')}?{urlencode({REDIRECT_FIELD_NAME: target})}")


class LoginFailedView(TemplateView):
    template_name = "authentication/login_failed.html"

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), **admin.site.each_context(self.request),
                "title": "Login not allowed", "switch_url": KeycloakLogout.url(self.request)}
