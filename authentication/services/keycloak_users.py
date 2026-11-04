from base.services.keycloak import KeycloakAdmin
from authentication.models import User


class KeycloakUserSync:
    SYNCED_FIELDS = ("email", "first_name", "last_name", "is_active", "is_superuser")

    def __init__(self):
        self.admin = KeycloakAdmin()

    def link_or_create(self, user, credential=None):
        if user.keycloak_id:
            return False
        found = self.admin.find(user.username)
        user.keycloak_id = found or self.admin.create(user, credential)
        User.objects.filter(id=user.id).update(keycloak_id=user.keycloak_id)
        return found is None

    def push(self, user):
        self.admin.update(user)
        self.admin.set_admin_group(user)
        if not user.is_active:
            self.admin.end_sessions(user)

    def save(self, user):
        created = self.link_or_create(user)
        self.push(user)
        return self.admin.set_temporary_password(user) if created else None

    def reset_password(self, user):
        self.link_or_create(user)
        return self.admin.set_temporary_password(user)

    def delete(self, user):
        if user.keycloak_id:
            self.admin.delete(user)

    def migrate(self, user):
        credential = self.admin.password_credential(user.password) if user.has_usable_password() else None
        created = self.link_or_create(user, credential)
        self.push(user)
        if created and credential:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            return "created, password imported"
        if created:
            return f"created, temporary password: {self.admin.set_temporary_password(user)}"
        return "already in Keycloak, updated"
