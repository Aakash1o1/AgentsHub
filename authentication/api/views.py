from django.contrib.auth.mixins import UserPassesTestMixin
from oauth2_provider.views import AuthorizationView


# This defines if user dosenot have a token, they will be sent to django login page
# If they are logged in but not super user, they will get 403 error
class SuperuserAuthorizationView(UserPassesTestMixin, AuthorizationView):
    def test_func(self):
        return self.request.user.is_superuser
