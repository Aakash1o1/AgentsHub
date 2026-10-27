from django.db import migrations


def llm_to_assistant(apps, schema_editor):
    # apps.get_model() gives the HISTORICAL Message -- the model as it exists at
    # this point in the migration history. Never import chat.models.Message here:
    # that is today's model, and replaying this migration on a fresh database
    # after the model changes again would behave differently or break.
    Message = apps.get_model("chat", "Message")
    Message.objects.filter(role="llm").update(role="assistant")


def assistant_to_llm(apps, schema_editor):
    Message = apps.get_model("chat", "Message")
    Message.objects.filter(role="assistant").update(role="llm")


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0008_alter_message_role"),
    ]

    operations = [
        # 0008 changed what Django allows in `role`; it emitted no SQL, because
        # `choices` lives only in Python. This rewrites the rows that predate it.
        # .update() issues one UPDATE statement and deliberately bypasses save(),
        # so auto_now does not bump updated_at for a rename that is not an edit.
        migrations.RunPython(llm_to_assistant, assistant_to_llm),
    ]
