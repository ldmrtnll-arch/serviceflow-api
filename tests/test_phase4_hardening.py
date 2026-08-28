from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.exceptions import NotFound, ValidationError

from apps.tickets.models import Ticket
from apps.tickets.services import create_ticket
from config.exceptions import api_exception_handler


@pytest.mark.django_db
def test_validation_errors_have_consistent_contract(api_client):
    response = api_client.post(reverse("register"), {}, format="json")
    assert response.status_code == 400
    assert response.data["code"] == "validation_error"
    assert response.data["detail"] == "The submitted data is invalid."
    assert "email" in response.data["errors"]


@pytest.mark.django_db
def test_authentication_and_not_found_errors_have_codes(api_client, requester):
    unauthenticated = api_client.get(reverse("me"))
    assert unauthenticated.status_code == 401
    assert unauthenticated.data["code"] == "not_authenticated"

    api_client.force_authenticate(requester)
    missing = api_client.get(reverse("ticket-detail", kwargs={"public_id": "not-a-uuid"}))
    assert missing.status_code == 404
    assert missing.data["code"] == "not_found"


def test_exception_handler_sanitizes_unexpected_errors(settings):
    settings.DEBUG = False
    response = api_exception_handler(RuntimeError("database password"), {})
    assert response.status_code == 500
    assert response.data == {
        "code": "internal_error",
        "detail": "An unexpected error occurred.",
    }


def test_exception_handler_keeps_standard_not_found_contract():
    response = api_exception_handler(NotFound("Missing"), {})
    assert response.data == {"code": "not_found", "detail": "Missing"}


def test_exception_handler_includes_nested_validation_errors():
    response = api_exception_handler(ValidationError({"field": ["Required"]}), {})
    assert response.data["code"] == "validation_error"
    assert response.data["errors"]["field"][0] == "Required"


@pytest.mark.django_db
def test_login_throttle_is_ip_scoped_and_returns_retry_after(api_client):
    cache.clear()
    url = reverse("login")
    for _ in range(10):
        response = api_client.post(url, {"email": "missing@example.com", "password": "bad"})
        assert response.status_code == 401
    response = api_client.post(url, {"email": "missing@example.com", "password": "bad"})
    assert response.status_code == 429
    assert response.data["code"] == "throttled"
    assert int(response["Retry-After"]) > 0


@pytest.mark.django_db
def test_ticket_list_query_count_is_bounded(api_client, agent, requester, category):
    Ticket.objects.bulk_create(
        [
            Ticket(
                requester=requester,
                category=category,
                title=f"Ticket {index}",
                description="Query regression fixture",
            )
            for index in range(30)
        ]
    )
    api_client.force_authenticate(agent)
    with CaptureQueriesContext(connection) as queries:
        response = api_client.get(reverse("ticket-list"))
    assert response.status_code == 200
    assert len(response.data["results"]) == 20
    assert len(queries) <= 4


@pytest.mark.django_db(transaction=True)
def test_broker_publish_failure_does_not_fail_committed_request(
    requester, category, monkeypatch, caplog
):
    monkeypatch.setattr(
        "apps.tickets.services.notify_ticket_event.delay",
        Mock(side_effect=ConnectionError("redis unavailable")),
    )
    with caplog.at_level("ERROR"):
        ticket = create_ticket(
            requester=requester,
            category=category,
            title="Broker outage",
            description="The database write must survive.",
        )
    assert Ticket.objects.filter(pk=ticket.pk).exists()
    assert "ticket_notification_publish_failed" in caplog.text
