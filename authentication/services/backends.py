from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Q
from django.urls import reverse
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from authentication.services.keycloak_users import TemporalAdmins
from authentication.services.members import MemberAccess


class KeycloakBackend(OIDCAuthenticationBackend):
    PROFILE_CLAIMS = {"email": "email", "given_name": "first_name", "family_name": "last_name"}

    def verify_claims(self, claims):
        return bool(claims.get("sub"))

    def filter_users_by_claims(self, claims):
        unlinked = Q(keycloak_id__isnull=True, username=claims.get("preferred_username"))
        return self.UserModel.objects.filter(Q(keycloak_id=claims["sub"]) | unlinked)

    def create_user(self, claims):
        user = self.UserModel(username=claims.get("preferred_username") or claims["sub"],
                              keycloak_id=claims["sub"], is_staff=True)
        for claim, field in self.PROFILE_CLAIMS.items():
            setattr(user, field, claims.get(claim) or "")
        user.set_unusable_password()
        user.save()
        MemberAccess.join(user)
        TemporalAdmins.sync(user)
        return user

    def update_user(self, user, claims):
        changed = [field for claim, field in self.PROFILE_CLAIMS.items()
                   if claim in claims and getattr(user, field) != claims[claim]]
        for claim, field in self.PROFILE_CLAIMS.items():
            if field in changed:
                setattr(user, field, claims[claim])
        if user.keycloak_id != claims["sub"]:
            user.keycloak_id = claims["sub"]
            changed.append("keycloak_id")
        if changed:
            user.save(update_fields=changed)
        TemporalAdmins.sync(user)
        return user

    def get_user(self, user_id):
        user = super().get_user(user_id)
        return user if user is not None and user.is_active else None


class KeycloakLogout:
    @staticmethod
    def url(request):
        params = {"post_logout_redirect_uri": request.build_absolute_uri(reverse("admin:login"))}
        id_token = request.session.get("oidc_id_token")
        if id_token:
            params["id_token_hint"] = id_token
        else:
            params["client_id"] = settings.OIDC_RP_CLIENT_ID
        return f"{settings.OIDC_OP_LOGOUT_ENDPOINT}?{urlencode(params)}"


keycloak_logout_url = KeycloakLogout.url
