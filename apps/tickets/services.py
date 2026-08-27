from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User

from .exceptions import (
    InvalidAssignee,
    InvalidTicketTransition,
    TicketAlreadyAssigned,
    TicketPermissionDenied,
)
from .models import Ticket, TicketHistory
from .tasks import notify_ticket_event

ALLOWED_TRANSITIONS = {
    Ticket.Status.OPEN: {Ticket.Status.IN_PROGRESS, Ticket.Status.CANCELLED},
    Ticket.Status.IN_PROGRESS: {
        Ticket.Status.WAITING_REQUESTER,
        Ticket.Status.RESOLVED,
        Ticket.Status.CANCELLED,
    },
    Ticket.Status.WAITING_REQUESTER: {
        Ticket.Status.IN_PROGRESS,
        Ticket.Status.RESOLVED,
        Ticket.Status.CANCELLED,
    },
    Ticket.Status.RESOLVED: {Ticket.Status.IN_PROGRESS, Ticket.Status.CLOSED},
    Ticket.Status.CLOSED: set(),
    Ticket.Status.CANCELLED: set(),
}


def _notify_after_commit(ticket: Ticket, event: str) -> None:
    transaction.on_commit(lambda: notify_ticket_event.delay(ticket.pk, event))


def _history(ticket, actor, action, field="", old_value="", new_value=""):
    return TicketHistory.objects.create(
        ticket=ticket,
        actor=actor,
        action=action,
        field=field,
        old_value=str(old_value or ""),
        new_value=str(new_value or ""),
    )


@transaction.atomic
def create_ticket(*, requester: User, **data) -> Ticket:
    ticket = Ticket.objects.create(requester=requester, status=Ticket.Status.OPEN, **data)
    _history(ticket, requester, TicketHistory.Action.CREATED, new_value=Ticket.Status.OPEN)
    _notify_after_commit(ticket, "created")
    return ticket


def _validate_operator(actor: User) -> None:
    if actor.role not in {User.Role.AGENT, User.Role.ADMIN}:
        raise TicketPermissionDenied("Only agents and administrators can perform this operation.")


def _validate_assignee(assignee: User | None) -> None:
    if assignee and assignee.role not in {User.Role.AGENT, User.Role.ADMIN}:
        raise InvalidAssignee("The assignee must be an agent or administrator.")


@transaction.atomic
def assign_ticket(*, ticket: Ticket, assignee: User | None, actor: User) -> Ticket:
    _validate_operator(actor)
    _validate_assignee(assignee)
    locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
    old_assignee = locked.assignee
    if old_assignee_id := locked.assignee_id:
        if assignee and old_assignee_id != assignee.pk and actor.role != User.Role.ADMIN:
            raise TicketAlreadyAssigned("Ticket is already assigned to another user.")
    if old_assignee == assignee:
        return locked
    locked.assignee = assignee
    locked.save(update_fields=["assignee", "updated_at"])
    action = TicketHistory.Action.ASSIGNED if assignee else TicketHistory.Action.UNASSIGNED
    _history(locked, actor, action, "assignee", old_assignee, assignee)
    _notify_after_commit(locked, "assigned" if assignee else "unassigned")
    return locked


def take_ownership(*, ticket: Ticket, actor: User) -> Ticket:
    return assign_ticket(ticket=ticket, assignee=actor, actor=actor)


@transaction.atomic
def transition_ticket(*, ticket: Ticket, target_status: str, actor: User) -> Ticket:
    locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
    allowed = ALLOWED_TRANSITIONS.get(locked.status, set())
    if target_status not in allowed:
        raise InvalidTicketTransition(
            f"Transition from {locked.status} to {target_status} is not allowed."
        )
    if actor.role == User.Role.REQUESTER:
        if actor.pk != locked.requester_id or target_status != Ticket.Status.CANCELLED:
            raise TicketPermissionDenied("Requester may only cancel their own active ticket.")
    if target_status == Ticket.Status.IN_PROGRESS and not locked.assignee_id:
        raise InvalidAssignee("A ticket needs an assignee before it can enter in_progress.")

    old_status = locked.status
    locked.status = target_status
    now = timezone.now()
    if target_status == Ticket.Status.RESOLVED:
        locked.resolved_at = now
    elif old_status == Ticket.Status.RESOLVED and target_status == Ticket.Status.IN_PROGRESS:
        locked.resolved_at = None
    if target_status == Ticket.Status.CLOSED:
        locked.closed_at = now
    locked.save(update_fields=["status", "resolved_at", "closed_at", "updated_at"])
    _history(
        locked,
        actor,
        TicketHistory.Action.STATUS_CHANGED,
        "status",
        old_status,
        target_status,
    )
    _notify_after_commit(locked, "status_changed")
    return locked


@transaction.atomic
def update_ticket(*, ticket: Ticket, actor: User, data: dict) -> Ticket:
    locked = Ticket.objects.select_for_update().get(pk=ticket.pk)
    if actor.role == User.Role.REQUESTER and locked.status != Ticket.Status.OPEN:
        raise TicketPermissionDenied("Requester can only edit a ticket while it is open.")

    actions: dict[str, tuple[str, Callable[[object], str]]] = {
        "priority": (TicketHistory.Action.PRIORITY_CHANGED, str),
        "category": (TicketHistory.Action.CATEGORY_CHANGED, lambda value: str(value.pk)),
        "title": (TicketHistory.Action.UPDATED, str),
        "description": (TicketHistory.Action.UPDATED, str),
    }
    changed_fields = []
    for field, value in data.items():
        old_value = getattr(locked, field)
        if old_value == value:
            continue
        setattr(locked, field, value)
        changed_fields.append(field)
        action, normalizer = actions[field]
        _history(locked, actor, action, field, normalizer(old_value), normalizer(value))
    if changed_fields:
        locked.save(update_fields=[*changed_fields, "updated_at"])
    return locked
