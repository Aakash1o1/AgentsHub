from django.db import migrations


class CopyDatasetFile:
    @staticmethod
    def forward(apps, schema_editor):
        Message = apps.get_model("chat", "Message")
        messages = list(Message.objects.exclude(dataset=None).select_related("dataset"))
        for message in messages:
            message.file = message.dataset.file.name
        Message.objects.bulk_update(messages, ["file"])


class Migration(migrations.Migration):

    dependencies = [
        ("analysis", "0003_remove_dataset_unique_dataset_table_per_vendor_and_more"),
        ("chat", "0018_message_file"),
    ]

    operations = [
        migrations.RunPython(CopyDatasetFile.forward, migrations.RunPython.noop),
    ]
