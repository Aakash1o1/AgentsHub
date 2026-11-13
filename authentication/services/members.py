from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Group


class MemberAccess:
    GROUP = "Members"
    PERMISSIONS = (
        ("chat", "view_chat"),
        ("chat", "change_chat"),
        ("chat", "view_message"),
        ("scraper", "view_document"),
        ("scraper", "add_document"),
        ("scraper", "change_document"),
        ("scraper", "view_chunk"),
        ("agent", "view_agent"),
    )

    @classmethod
    def sync(cls, apps):
        for app_config in apps.get_app_configs():
            app_config.models_module = True
            create_permissions(app_config, apps=apps, verbosity=0)
            app_config.models_module = None
        HistoricalGroup = apps.get_model("auth", "Group")
        Permission = apps.get_model("auth", "Permission")
        group, _ = HistoricalGroup.objects.get_or_create(name=cls.GROUP)
        wanted = [Permission.objects.get(content_type__app_label=app, codename=codename) for app, codename in cls.PERMISSIONS]
        group.permissions.set(wanted)
        User = apps.get_model("authentication", "User")
        for user in User.objects.filter(is_superuser=False):
            user.groups.add(group)

    @classmethod
    def join(cls, user):
        group, _ = Group.objects.get_or_create(name=cls.GROUP)
        user.groups.add(group)
