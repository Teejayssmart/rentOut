from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0031_remove_room_uq_room_title_lower_alive_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="updated",
            field=models.DateTimeField(auto_now=True, db_index=True),
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(fields=["thread", "updated"], name="message_thread_updated_idx"),
        ),
    ]
