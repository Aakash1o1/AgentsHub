from urllib.parse import unquote, urlparse

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import migrations, models


class AttachmentUrls:
    @staticmethod
    def messages(apps):
        return apps.get_model("chat", "Message").objects.exclude(attachment="")

    @classmethod
    def forwards(cls, apps, schema_editor):
        for message in cls.messages(apps):
            if not message.attachment.startswith("http"):
                cls.messages(apps).filter(id=message.id).update(
                    attachment=settings.SITE_URL + default_storage.url(message.attachment))

    @classmethod
    def backwards(cls, apps, schema_editor):
        media = default_storage.url("")
        for message in cls.messages(apps):
            path = unquote(urlparse(message.attachment).path).removeprefix(media)
            cls.messages(apps).filter(id=message.id).update(attachment=path)


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0030_alter_chat_options'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='attachment',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.RunPython(AttachmentUrls.forwards, AttachmentUrls.backwards),
    ]
