from django.core.management.base import BaseCommand

from authentication.models import User
from authentication.services.keycloak_users import KeycloakUserSync
from base.services.keycloak import KeycloakError


class Command(BaseCommand):
    help = "Create every Django user in Keycloak (importing the password) and update the ones already there"

    def add_arguments(self, parser):
        parser.add_argument("usernames", nargs="*")

    def handle(self, *args, **options):
        sync = KeycloakUserSync()
        users = User.objects.order_by("id")
        if options["usernames"]:
            users = users.filter(username__in=options["usernames"])
        for user in users:
            try:
                self.stdout.write(f"{user.username}: {sync.migrate(user)}")
            except KeycloakError as e:
                self.stderr.write(f"{user.username}: failed, {e}")
