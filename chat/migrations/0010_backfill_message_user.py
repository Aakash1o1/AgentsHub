from django.db import migrations
from django.db.models import OuterRef, Subquery


def fill_user_from_chat(apps, schema_editor):
    Message = apps.get_model("chat", "Message")
    Chat = apps.get_model("chat", "Chat")
    owner = Chat.objects.filter(pk=OuterRef("chat_id")).values("user_id")[:1]
    Message.objects.filter(user_id__isnull=True, chat_id__isnull=False).update(
        user_id=Subquery(owner)
    )


def clear_user(apps, schema_editor):
    Message = apps.get_model("chat", "Message")
    Chat = apps.get_model("chat", "Chat")
    owner = Chat.objects.filter(pk=OuterRef("chat_id")).values("user_id")[:1]
    Message.objects.filter(chat_id__isnull=False, user_id=Subquery(owner)).update(
        user_id=None
    )


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0009_message_role_llm_to_assistant"),
    ]

    operations = [
        migrations.RunPython(fill_user_from_chat, clear_user),
    ]
