import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .exceptions import SLAPolicyNotConfigured
from .models import SLAPolicy, Ticket, TicketHistory

logger = logging.getLogger(__name__)


def resolve_sla_policy(priority: str) -> SLAPolicy:
    try:
        return SLAPolicy.objects.get(priority=priority, is_active=True)
    except SLAPolicy.DoesNotExist as exc:
        raise SLAPolicyNotConfigured(
            f"No active SLA policy is configured for priority '{priority}'."
        ) from exc


def calculate_deadlines(created_at, policy: SLAPolicy):
    return (
        created_at + timedelta(minutes=policy.first_response_minutes),
        created_at + timedelta(minutes=policy.resolution_minutes),
    )


def apply_sla_policy(ticket: Ticket, policy: SLAPolicy) -> None:
    ticket.first_response_due_at, ticket.resolution_due_at = calculate_deadlines(
        ticket.created_at, policy
    )
    logger.info(
        "sla_policy_applied ticket_id=%s priority=%s first_response_due_at=%s resolution_due_at=%s",
        ticket.public_id,
        ticket.priority,
        ticket.first_response_due_at.isoformat(),
        ticket.resolution_due_at.isoformat(),
        extra={
            "ticket_id": str(ticket.public_id),
            "priority": ticket.priority,
            "first_response_due_at": ticket.first_response_due_at.isoformat(),
            "resolution_due_at": ticket.resolution_due_at.isoformat(),
        },
    )


def _record_history(ticket: Ticket, action: str, occurred_at) -> None:
    TicketHistory.objects.create(
        ticket=ticket,
        actor=None,
        action=action,
        field="sla",
        new_value=occurred_at.isoformat(),
    )


def mark_due_breaches(ticket: Ticket, *, now=None) -> list[str]:
    from .services import _notify_after_commit

    now = now or timezone.now()
    if ticket.status == Ticket.Status.CANCELLED:
        return []
    events = []
    if (
        ticket.first_response_due_at
        and ticket.first_responded_at is None
        and ticket.sla_first_response_breached_at is None
        and now > ticket.first_response_due_at
    ):
        ticket.sla_first_response_breached_at = now
        _record_history(ticket, TicketHistory.Action.SLA_FIRST_RESPONSE_BREACHED, now)
        events.append("sla_first_response_breached")
    if (
        ticket.resolution_due_at
        and ticket.first_resolved_at is None
        and ticket.sla_resolution_breached_at is None
        and now > ticket.resolution_due_at
    ):
        ticket.sla_resolution_breached_at = now
        _record_history(ticket, TicketHistory.Action.SLA_RESOLUTION_BREACHED, now)
        events.append("sla_resolution_breached")
    if events:
        ticket.save(
            update_fields=[
                "sla_first_response_breached_at",
                "sla_resolution_breached_at",
                "updated_at",
            ]
        )
        for event in events:
            logger.info(
                "%s ticket_id=%s occurred_at=%s",
                event,
                ticket.public_id,
                now.isoformat(),
                extra={"ticket_id": str(ticket.public_id), "occurred_at": now},
            )
            _notify_after_commit(ticket, event)
    return events


@transaction.atomic
def check_ticket_sla(ticket_id: int, *, now=None) -> list[str]:
    ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
    return mark_due_breaches(ticket, now=now)


def check_all_sla_breaches(*, now=None) -> dict[str, int]:
    now = now or timezone.now()
    first_response_ids = (
        Ticket.objects.filter(
            first_responded_at__isnull=True,
            first_response_due_at__lt=now,
            sla_first_response_breached_at__isnull=True,
        )
        .exclude(status=Ticket.Status.CANCELLED)
        .values_list("pk", flat=True)
    )
    resolution_ids = (
        Ticket.objects.filter(
            first_resolved_at__isnull=True,
            resolution_due_at__lt=now,
            sla_resolution_breached_at__isnull=True,
        )
        .exclude(status__in=[Ticket.Status.CANCELLED, Ticket.Status.RESOLVED, Ticket.Status.CLOSED])
        .values_list("pk", flat=True)
    )
    candidate_ids = set(first_response_ids) | set(resolution_ids)
    counts = {"checked": len(candidate_ids), "first_response_breaches": 0, "resolution_breaches": 0}
    for ticket_id in candidate_ids:
        events = check_ticket_sla(ticket_id, now=now)
        counts["first_response_breaches"] += "sla_first_response_breached" in events
        counts["resolution_breaches"] += "sla_resolution_breached" in events
    logger.info(
        "sla_check_completed checked=%s first_response_breaches=%s resolution_breaches=%s",
        counts["checked"],
        counts["first_response_breaches"],
        counts["resolution_breaches"],
        extra=counts,
    )
    return counts


def recalculate_sla_deadlines(ticket: Ticket, priority: str, *, now=None) -> list[str]:
    policy = resolve_sla_policy(priority)
    apply_sla_policy(ticket, policy)
    logger.info(
        "sla_deadline_recalculated ticket_id=%s priority=%s",
        ticket.public_id,
        priority,
        extra={"ticket_id": str(ticket.public_id), "priority": priority},
    )
    return mark_due_breaches(ticket, now=now)
