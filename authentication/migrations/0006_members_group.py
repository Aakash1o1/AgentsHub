from django.db import migrations

from authentication.services.members import MemberAccess


class MembersGroup:
    @staticmethod
    def forwards(apps, schema_editor):
        MemberAccess.sync(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("authentication", "0005_user_keycloak_id"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("chat", "0029_remove_message_summary"),
        ("scraper", "0008_alter_document_status"),
        ("agent", "0007_agent_workflow_start_node"),
    ]

    operations = [
        migrations.RunPython(MembersGroup.forwards, migrations.RunPython.noop),
    ]
