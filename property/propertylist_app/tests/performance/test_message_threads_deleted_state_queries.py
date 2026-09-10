import pytest

from rest_framework.test import APIRequestFactory, force_authenticate

from propertylist_app.api.views.messaging import MessageThreadListCreateView
from propertylist_app.models import MessageThread, MessageThreadState, UserProfile


@pytest.mark.django_db
def test_message_thread_list_does_not_query_each_deleted_thread_state(
    django_user_model,
    django_assert_num_queries,
):
    user = django_user_model.objects.create_user(
        username="message_thread_perf_user",
        email="message_thread_perf_user@example.com",
        password="testpass123",
    )
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    from django.utils import timezone

    deleted_at = timezone.now()

    for _ in range(4):
        thread = MessageThread.objects.create()
        thread.participants.add(user)
        MessageThreadState.objects.create(
            user=user,
            thread=thread,
            deleted_at=deleted_at,
        )

    factory = APIRequestFactory()
    django_request = factory.get("/api/v1/messages/threads/")
    force_authenticate(django_request, user=user)

    view = MessageThreadListCreateView()
    request = view.initialize_request(django_request)
    view.request = request
    view.args = ()
    view.kwargs = {}

    # Building the queryset should do only the fixed-cost profile lookup and
    # bin-state lookup. The number of deleted thread states must not add one
    # Message EXISTS query per state.
    with django_assert_num_queries(2):
        view.get_queryset()
