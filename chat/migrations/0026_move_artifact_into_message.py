import json

from django.db import migrations


class ArtifactInMessage:
    MARKER = "<!--artifact-->"

    @classmethod
    def forward(cls, apps, schema_editor):
        Message = apps.get_model("chat", "Message")
        for message in Message.objects.filter(artifact__isnull=False).only("id", "message", "artifact"):
            text = message.message.replace(cls.MARKER, "")
            Message.objects.filter(pk=message.pk).update(message=f"{text}\n{cls.MARKER}{json.dumps(message.artifact)}")

    @classmethod
    def backward(cls, apps, schema_editor):
        Message = apps.get_model("chat", "Message")
        for message in Message.objects.filter(role="assistant", message__contains=cls.MARKER).only("id", "message"):
            text, _, tail = message.message.rpartition(cls.MARKER)
            try:
                artifact = json.loads(tail)
            except ValueError:
                continue
            Message.objects.filter(pk=message.pk).update(message=text.removesuffix("\n"), artifact=artifact)


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0025_message_document_message_source_type_message_url"),
    ]

    operations = [
        migrations.RunPython(ArtifactInMessage.forward, ArtifactInMessage.backward),
        migrations.RemoveField(model_name="message", name="artifact"),
    ]
