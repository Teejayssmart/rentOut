from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0029_roomimage_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="avatar",
            field=models.ImageField(upload_to="avatars/", null=True, blank=True),
        ),
    ]
