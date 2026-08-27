from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from freezegun import freeze_time

from apps.tickets.exceptions import SLAPolicyNotConfigured
from apps.tickets.models import SLAPolicy, Ticket, TicketHistory
from apps.tickets.services import (
    add_ticket_comment,
    create_ticket,
    transition_ticket,
    update_ticket,
)
from apps.tickets.sla import check_all_sla_breaches
from apps.tickets.tasks import check_sla_breaches


@pytest.mark.django_db
def test_policy_validates_positive_and_ordered_durations():
    policy = SLAPolicy(
        name="Invalid",
        priority=Ticket.Priority.LOW,
        first_response_minutes=0,
        resolution_minutes=0,
    )
    with pytest.raises(ValidationError) as error:
        policy.full_clean()
    assert "first_response_minutes" in error.value.message_dict
    assert "resolution_minutes" in error.value.message_dict

    policy.first_response_minutes = 60
    policy.resolution_minutes = 30
    with pytest.raises(ValidationError):
        policy.full_clean()


@pytest.mark.django_db(transaction=True)
def test_database_prevents_two_active_policies_for_priority():
    SLAPolicy.objects.create(
        name="Primary",
        priority=Ticket.Priority.HIGH,
        first_response_minutes=60,
        resolution_minutes=120,
    )
    with pytest.raises(IntegrityError):
        SLAPolicy.objects.create(
            name="Conflict",
            priority=Ticket.Priority.HIGH,
            first_response_minutes=30,
            resolution_minutes=60,
        )


@pytest.mark.django_db
def test_missing_policy_is_explicit_domain_error(requester, category):
    SLAPolicy.objects.filter(priority=Ticket.Priority.URGENT).delete()
    with pytest.raises(SLAPolicyNotConfigured):
        create_ticket(
            requester=requester,
            category=category,
            title="Urgent",
            description="No policy",
            priority=Ticket.Priority.URGENT,
        )


@pytest.mark.parametrize(
    ("priority", "response_minutes", "resolution_minutes"),
    [
        (Ticket.Priority.LOW, 1440, 7200),
        (Ticket.Priority.MEDIUM, 480, 4320),
        (Ticket.Priority.HIGH, 240, 1440),
        (Ticket.Priority.URGENT, 60, 480),
    ],
)
@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_creation_freezes_deadlines(
    priority, response_minutes, resolution_minutes, requester, category
):
    ticket = create_ticket(
        requester=requester,
        category=category,
        title="Deadline test",
        description="Fixed time",
        priority=priority,
    )
    assert timezone.is_aware(ticket.first_response_due_at)
    assert ticket.first_response_due_at == ticket.created_at + timedelta(minutes=response_minutes)
    assert ticket.resolution_due_at == ticket.created_at + timedelta(minutes=resolution_minutes)


@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_policy_edit_only_affects_future_tickets(requester, category):
    old_ticket = create_ticket(
        requester=requester,
        category=category,
        title="Old",
        description="Old policy",
        priority=Ticket.Priority.MEDIUM,
    )
    old_deadline = old_ticket.first_response_due_at
    policy = SLAPolicy.objects.get(priority=Ticket.Priority.MEDIUM, is_active=True)
    policy.first_response_minutes = 120
    policy.save()

    new_ticket = create_ticket(
        requester=requester,
        category=category,
        title="New",
        description="New policy",
        priority=Ticket.Priority.MEDIUM,
    )
    old_ticket.refresh_from_db()
    assert old_ticket.first_response_due_at == old_deadline
    assert new_ticket.first_response_due_at == new_ticket.created_at + timedelta(minutes=120)


@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_priority_change_recalculates_from_creation(requester, category, agent):
    ticket = create_ticket(
        requester=requester,
        category=category,
        title="Reclassify",
        description="Priority changes",
        priority=Ticket.Priority.MEDIUM,
    )
    with freeze_time("2026-01-10 10:30:00", tz_offset=0):
        ticket = update_ticket(
            ticket=ticket, actor=agent, data={"priority": Ticket.Priority.URGENT}
        )
    assert ticket.first_response_due_at == ticket.created_at + timedelta(minutes=60)
    assert ticket.resolution_due_at == ticket.created_at + timedelta(minutes=480)


@pytest.mark.django_db(transaction=True)
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_priority_change_can_create_immediate_idempotent_breach(
    requester, category, agent, monkeypatch
):
    notifications = []
    monkeypatch.setattr(
        "apps.tickets.tasks.notify_ticket_event.delay",
        lambda ticket_id, event: notifications.append((ticket_id, event)),
    )
    ticket = create_ticket(
        requester=requester,
        category=category,
        title="Reclassify late",
        description="Immediate breach",
        priority=Ticket.Priority.MEDIUM,
    )
    notifications.clear()
    with freeze_time("2026-01-10 12:00:00", tz_offset=0):
        ticket = update_ticket(
            ticket=ticket, actor=agent, data={"priority": Ticket.Priority.URGENT}
        )
        original_breach = ticket.sla_first_response_breached_at
        update_ticket(ticket=ticket, actor=agent, data={"title": "No duplicate"})

    assert original_breach is not None
    assert (
        ticket.history.filter(action=TicketHistory.Action.SLA_FIRST_RESPONSE_BREACHED).count() == 1
    )
    assert [event for _, event in notifications].count("sla_first_response_breached") == 1


@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_requester_comment_does_not_complete_first_response(requester, category):
    ticket = create_ticket(
        requester=requester, category=category, title="Question", description="Details"
    )
    add_ticket_comment(ticket=ticket, author=requester, content="More details")
    ticket.refresh_from_db()
    assert ticket.first_responded_at is None


@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_first_operator_comment_completes_response_once(requester, category, agent, admin_user):
    ticket = create_ticket(
        requester=requester, category=category, title="Question", description="Details"
    )
    with freeze_time("2026-01-10 11:00:00", tz_offset=0):
        add_ticket_comment(ticket=ticket, author=agent, content="First response")
    ticket.refresh_from_db()
    first_response = ticket.first_responded_at
    with freeze_time("2026-01-10 12:00:00", tz_offset=0):
        add_ticket_comment(ticket=ticket, author=admin_user, content="Follow-up")
    ticket.refresh_from_db()
    assert ticket.first_responded_at == first_response
    assert ticket.first_response_sla_status == "met"
    assert (
        ticket.history.filter(action=TicketHistory.Action.SLA_FIRST_RESPONSE_COMPLETED).count() == 1
    )


@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_late_operator_response_is_breached(requester, category, agent):
    ticket = create_ticket(
        requester=requester,
        category=category,
        title="Urgent response",
        description="Details",
        priority=Ticket.Priority.URGENT,
    )
    with freeze_time("2026-01-10 11:00:01", tz_offset=0):
        add_ticket_comment(ticket=ticket, author=agent, content="Late response")
    ticket.refresh_from_db()
    assert ticket.sla_first_response_breached_at == ticket.first_responded_at
    assert ticket.first_response_sla_status == "breached"


@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_resolution_at_deadline_is_met_and_reopen_preserves_first_resolution(
    requester, category, agent
):
    ticket = create_ticket(
        requester=requester,
        category=category,
        title="Urgent resolution",
        description="Details",
        priority=Ticket.Priority.URGENT,
    )
    ticket.assignee = agent
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save()
    with freeze_time("2026-01-10 18:00:00", tz_offset=0):
        ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.RESOLVED, actor=agent)
    first_resolution = ticket.first_resolved_at
    assert ticket.resolution_sla_status == "met"

    ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.IN_PROGRESS, actor=agent)
    assert ticket.resolved_at is None
    assert ticket.first_resolved_at == first_resolution
    ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.RESOLVED, actor=agent)
    assert ticket.first_resolved_at == first_resolution


@pytest.mark.django_db
@freeze_time("2026-01-10 10:00:00", tz_offset=0)
def test_late_first_resolution_records_breach(requester, category, agent):
    ticket = create_ticket(
        requester=requester,
        category=category,
        title="Late resolution",
        description="Details",
        priority=Ticket.Priority.URGENT,
    )
    ticket.assignee = agent
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save()
    with freeze_time("2026-01-10 18:00:01", tz_offset=0):
        ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.RESOLVED, actor=agent)
    assert ticket.sla_resolution_breached_at == ticket.first_resolved_at
    assert ticket.history.filter(action=TicketHistory.Action.SLA_RESOLUTION_BREACHED).count() == 1


@pytest.mark.django_db(transaction=True)
@freeze_time("2026-01-10 12:00:00", tz_offset=0)
def test_periodic_check_is_idempotent(ticket, monkeypatch):
    notifications = []
    monkeypatch.setattr(
        "apps.tickets.tasks.notify_ticket_event.delay",
        lambda ticket_id, event: notifications.append((ticket_id, event)),
    )
    ticket.first_response_due_at = timezone.now() - timedelta(hours=1)
    ticket.resolution_due_at = timezone.now() - timedelta(minutes=1)
    ticket.save()

    first = check_all_sla_breaches()
    ticket.refresh_from_db()
    first_timestamp = ticket.sla_first_response_breached_at
    second = check_all_sla_breaches()
    ticket.refresh_from_db()

    assert first == {"checked": 1, "first_response_breaches": 1, "resolution_breaches": 1}
    assert second == {"checked": 0, "first_response_breaches": 0, "resolution_breaches": 0}
    assert ticket.sla_first_response_breached_at == first_timestamp
    assert (
        ticket.history.filter(action=TicketHistory.Action.SLA_FIRST_RESPONSE_BREACHED).count() == 1
    )
    assert len(notifications) == 2


@pytest.mark.django_db
@freeze_time("2026-01-10 12:00:00", tz_offset=0)
def test_cancelled_ticket_is_not_breached(ticket):
    ticket.status = Ticket.Status.CANCELLED
    ticket.first_response_due_at = timezone.now() - timedelta(hours=1)
    ticket.resolution_due_at = timezone.now() - timedelta(hours=1)
    ticket.save()
    assert check_all_sla_breaches()["checked"] == 0
    ticket.refresh_from_db()
    assert ticket.first_response_sla_status == "not_applicable"
    assert ticket.resolution_sla_status == "not_applicable"


def test_celery_task_delegates_to_sla_service(monkeypatch):
    expected = {"checked": 2, "first_response_breaches": 1, "resolution_breaches": 1}
    monkeypatch.setattr("apps.tickets.sla.check_all_sla_breaches", lambda: expected)
    assert check_sla_breaches() == expected
