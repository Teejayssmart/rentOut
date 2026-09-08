from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0096_messagethreadstate_deleted_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="relisted_at",
            field=models.DateTimeField(default=None, null=True),
        ),
    ]
