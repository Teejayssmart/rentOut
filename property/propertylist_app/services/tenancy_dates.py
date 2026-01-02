from datetime import datetime, timedelta, time
from dateutil.relativedelta import relativedelta
from django.utils import timezone


def compute_end_date(move_in_date, duration_months):
    # accurate calendar month maths
    return move_in_date + relativedelta(months=+int(duration_months))


def compute_review_window(move_in_date, duration_months):
    end_date = compute_end_date(move_in_date, duration_months)

    # use midnight of end_date in current timezone to keep dates stable
    end_midnight = timezone.make_aware(datetime.combine(end_date, time.min))

    review_open_at = end_midnight + timedelta(days=7)
    review_deadline_at = review_open_at + timedelta(days=60)
    still_living_check_at = end_midnight - timedelta(days=7)

    return review_open_at, review_deadline_at, still_living_check_at
