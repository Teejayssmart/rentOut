from django.conf import settings
from django.db import migrations


def create_review_table_if_missing(apps, schema_editor):
    Review = apps.get_model("propertylist_app", "Review")
    table_name = Review._meta.db_table

    existing_tables = schema_editor.connection.introspection.table_names()
    if table_name in existing_tables:
        return

    schema_editor.create_model(Review)


class Migration(migrations.Migration):
    dependencies = [
        ("propertylist_app", "0062_room_accessible_entry_room_bathroom_type_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(create_review_table_if_missing, migrations.RunPython.noop),
    ]
