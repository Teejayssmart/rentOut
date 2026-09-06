from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower


class Migration(migrations.Migration):

    dependencies = [
        ("propertylist_app", "0096_messagethreadstate_deleted_at_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="room",
            name="uq_room_title_lower_alive",
        ),
        migrations.AddConstraint(
            model_name="room",
            constraint=models.UniqueConstraint(
                Lower("title"),
                "property_owner",
                condition=Q(is_deleted=False),
                name="uq_room_owner_title_lower_alive",
            ),
        ),
    ]
