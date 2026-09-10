from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0096_messagethreadstate_deleted_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenancy",
            name="source_booking",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tenancies_proposed",
                to="propertylist_app.booking",
            ),
        ),
    ]
