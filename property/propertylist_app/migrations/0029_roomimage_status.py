from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0028_notification"),  # adjust if your latest migration differs
    ]

    operations = [
        migrations.AddField(
            model_name="roomimage",
            name="status",
            field=models.CharField(
                default="pending",
                choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
                max_length=16,
                db_index=True,
            ),
        ),
    ]
