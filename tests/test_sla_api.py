from datetime import timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.tickets.models import SLAPolicy, Ticket
from apps.tickets.services import create_ticket


@pytest.mark.django_db
def test_seed_creates_default_policies_idempotently():
    call_command("seed_dev")
    call_command("seed_dev")
    policies = SLAPolicy.objects.filter(is_active=True)
    assert policies.count() == 4
    urgent = policies.get(priority=Ticket.Priority.URGENT)
    assert (urgent.first_response_minutes, urgent.resolution_minutes) == (60, 480)


@pytest.mark.django_db
def test_requester_cannot_access_or_modify_policies(api_client, requester, category):
    api_client.force_authenticate(requester)
    assert api_client.get(reverse("sla-policy-list")).status_code == 403
    assert (
        api_client.post(
            reverse("sla-policy-list"),
            {
                "name": "Forbidden",
                "priority": "urgent",
                "first_response_minutes": 10,
                "resolution_minutes": 20,
            },
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_agent_reads_and_admin_manages_policies(api_client, agent, admin_user, category):
    api_client.force_authenticate(agent)
    assert api_client.get(reverse("sla-policy-list")).data["count"] == 4
    assert api_client.post(reverse("sla-policy-list"), {}).status_code == 403

    existing = SLAPolicy.objects.get(priority=Ticket.Priority.LOW)
    existing.is_active = False
    existing.save()
    api_client.force_authenticate(admin_user)
    response = api_client.post(
        reverse("sla-policy-list"),
        {
            "name": "New low",
            "priority": "low",
            "first_response_minutes": 30,
            "resolution_minutes": 120,
        },
        format="json",
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_policy_api_rejects_invalid_duration_and_active_conflict(api_client, admin_user, category):
    api_client.force_authenticate(admin_user)
    invalid = api_client.post(
        reverse("sla-policy-list"),
        {
            "name": "Invalid",
            "priority": "low",
            "first_response_minutes": 60,
            "resolution_minutes": 30,
            "is_active": False,
        },
        format="json",
    )
    assert invalid.status_code == 400
    conflict = api_client.post(
        reverse("sla-policy-list"),
        {
            "name": "Conflict",
            "priority": "low",
            "first_response_minutes": 30,
            "resolution_minutes": 60,
        },
        format="json",
    )
    assert conflict.status_code == 400


@pytest.mark.django_db
def test_ticket_detail_exposes_read_only_sla(api_client, requester, category):
    ticket = create_ticket(
        requester=requester, category=category, title="SLA API", description="Details"
    )
    api_client.force_authenticate(requester)
    response = api_client.get(reverse("ticket-detail", kwargs={"public_id": ticket.public_id}))
    assert response.status_code == 200
    assert response.data["sla"]["first_response"]["status"] == "pending"
    assert response.data["first_response_due_at"] is not None

    original_due = ticket.first_response_due_at
    api_client.patch(
        reverse("ticket-detail", kwargs={"public_id": ticket.public_id}),
        {"first_response_due_at": "2000-01-01T00:00:00Z", "title": "Safe update"},
        format="json",
    )
    ticket.refresh_from_db()
    assert ticket.first_response_due_at == original_due


@pytest.mark.django_db
def test_sla_filter_preserves_requester_isolation(api_client, requester, other_requester, category):
    own = create_ticket(
        requester=requester, category=category, title="Own breach", description="Visible"
    )
    other = create_ticket(
        requester=other_requester, category=category, title="Other breach", description="Hidden"
    )
    breach_time = timezone.now()
    Ticket.objects.filter(pk__in=[own.pk, other.pk]).update(
        sla_first_response_breached_at=breach_time
    )
    api_client.force_authenticate(requester)
    response = api_client.get(reverse("ticket-list"), {"sla_status": "breached"})
    assert response.data["count"] == 1
    assert response.data["results"][0]["id"] == str(own.public_id)


@pytest.mark.django_db
def test_metrics_are_operator_only_and_use_database_aggregates(
    api_client, requester, agent, admin_user, category
):
    first = create_ticket(
        requester=requester, category=category, title="First", description="Metrics"
    )
    second = create_ticket(
        requester=requester, category=category, title="Second", description="Metrics"
    )
    now = timezone.now()
    Ticket.objects.filter(pk=first.pk).update(
        status=Ticket.Status.IN_PROGRESS,
        first_responded_at=now,
        sla_first_response_breached_at=now,
    )
    Ticket.objects.filter(pk=second.pk).update(
        status=Ticket.Status.RESOLVED,
        first_resolved_at=now + timedelta(minutes=30),
        resolved_at=now + timedelta(minutes=30),
        sla_resolution_breached_at=now,
    )

    api_client.force_authenticate(requester)
    assert api_client.get(reverse("ticket-metrics")).status_code == 403
    for operator in (agent, admin_user):
        api_client.force_authenticate(operator)
        response = api_client.get(reverse("ticket-metrics"))
        assert response.status_code == 200
        assert response.data["total"] == 2
        assert response.data["in_progress"] == 1
        assert response.data["resolved"] == 1
        assert response.data["sla"]["first_response_breached"] == 1
        assert response.data["sla"]["resolution_breached"] == 1
