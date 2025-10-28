import datetime as dt
from django.utils import timezone
from propertylist_app.models import Room
from propertylist_app.tasks import task_expire_paid_listings

def test_expire_paid_listings_marks_hidden(db):
    r = Room.objects.create(
        title="Test", description="d", price_per_month=500, location="L",
        paid_until=timezone.localdate() - dt.timedelta(days=1)
    )
    assert r.status == "active"
    res = task_expire_paid_listings()
    r.refresh_from_db()
    assert r.status == "hidden"
    assert res >= 1   # just compare the integer result

