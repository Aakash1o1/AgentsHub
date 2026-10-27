from django.db import migrations
from django.db.models import F


def fill_audit_from_user(apps, schema_editor):
    Message = apps.get_model("chat", "Message")
    Message.objects.filter(created_by_id__isnull=True, user_id__isnull=False).update(
        created_by_id=F("user_id")
    )
    Message.objects.filter(updated_by_id__isnull=True, user_id__isnull=False).update(
        updated_by_id=F("user_id")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0010_backfill_message_user"),
    ]

    operations = [
        # Not reversible: rows that already had created_by set are
        # indistinguishable afterwards, so nulling them back would destroy data
        # this migration never touched.
        migrations.RunPython(fill_audit_from_user, migrations.RunPython.noop),
    ]
