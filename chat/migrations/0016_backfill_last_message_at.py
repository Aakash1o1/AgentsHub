from django.db import migrations
from django.db.models import Max, OuterRef, Subquery
from django.db.models.functions import Coalesce


class BackfillLastMessageAt:
    @staticmethod
    def forward(apps, schema_editor):
        Chat = apps.get_model("chat", "Chat")
        Message = apps.get_model("chat", "Message")
        latest = (
            Message.objects.filter(chat=OuterRef("pk"))
            .order_by()
            .values("chat")
            .annotate(latest=Max("created_at"))
            .values("latest")
        )
        Chat.objects.update(last_message_at=Coalesce(Subquery(latest), "created_at"))


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0015_chat_last_message_at'),
    ]

    operations = [
        migrations.RunPython(BackfillLastMessageAt.forward, migrations.RunPython.noop),
    ]
