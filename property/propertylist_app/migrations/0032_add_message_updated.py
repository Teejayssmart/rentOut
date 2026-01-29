from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0031_remove_room_uq_room_title_lower_alive_and_more"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE INDEX IF NOT EXISTS message_thread_updated_idx
            ON propertylist_app_message (thread_id, updated);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS message_thread_updated_idx;
            """,
        ),
    ]
