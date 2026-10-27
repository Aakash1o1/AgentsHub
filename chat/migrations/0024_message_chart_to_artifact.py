from django.db import migrations


class ArtifactKind:
    @staticmethod
    def add(apps, schema_editor):
        Message = apps.get_model("chat", "Message")
        for message in Message.objects.filter(artifact__isnull=False):
            message.artifact = {"kind": "chart", **message.artifact}
            message.save(update_fields=["artifact"])

    @staticmethod
    def remove(apps, schema_editor):
        Message = apps.get_model("chat", "Message")
        for message in Message.objects.filter(artifact__kind="chart"):
            message.artifact = {key: value for key, value in message.artifact.items() if key != "kind"}
            message.save(update_fields=["artifact"])


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0023_rename_message_file_to_attachment"),
    ]

    operations = [
        migrations.RenameField(model_name="message", old_name="chart", new_name="artifact"),
        migrations.RunPython(ArtifactKind.add, ArtifactKind.remove),
    ]
