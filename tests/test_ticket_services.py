import pytest

from apps.accounts.models import User
from apps.tickets.exceptions import (
    InvalidAssignee,
    InvalidTicketTransition,
    TicketAlreadyAssigned,
    TicketPermissionDenied,
)
from apps.tickets.models import Ticket, TicketHistory
from apps.tickets.services import (
    assign_ticket,
    create_ticket,
    take_ownership,
    transition_ticket,
    update_ticket,
)


@pytest.mark.django_db(transaction=True)
def test_create_ticket_sets_server_state_and_history(requester, category, monkeypatch):
    monkeypatch.setattr("apps.tickets.tasks.notify_ticket_event.delay", lambda *args: None)
    ticket = create_ticket(
        requester=requester,
        category=category,
        title="New ticket",
        description="Details",
        priority=Ticket.Priority.HIGH,
    )
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.assignee is None
    assert ticket.history.get().action == TicketHistory.Action.CREATED


@pytest.mark.django_db
def test_in_progress_requires_assignee(ticket, agent):
    with pytest.raises(InvalidAssignee):
        transition_ticket(ticket=ticket, target_status=Ticket.Status.IN_PROGRESS, actor=agent)


@pytest.mark.django_db
def test_full_resolution_and_reopen_flow(ticket, agent):
    ticket = take_ownership(ticket=ticket, actor=agent)
    ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.IN_PROGRESS, actor=agent)
    ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.RESOLVED, actor=agent)
    assert ticket.resolved_at is not None

    ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.IN_PROGRESS, actor=agent)
    assert ticket.resolved_at is None
    assert ticket.history.filter(action=TicketHistory.Action.STATUS_CHANGED).count() == 3


@pytest.mark.django_db
def test_closing_sets_timestamp_and_terminal_state(ticket, agent):
    ticket.assignee = agent
    ticket.status = Ticket.Status.RESOLVED
    ticket.save()
    ticket = transition_ticket(ticket=ticket, target_status=Ticket.Status.CLOSED, actor=agent)
    assert ticket.closed_at is not None
    with pytest.raises(InvalidTicketTransition):
        transition_ticket(ticket=ticket, target_status=Ticket.Status.IN_PROGRESS, actor=agent)


@pytest.mark.django_db
def test_requester_can_only_cancel_own_ticket(ticket, requester, other_requester):
    cancelled = transition_ticket(
        ticket=ticket, target_status=Ticket.Status.CANCELLED, actor=requester
    )
    assert cancelled.status == Ticket.Status.CANCELLED

    ticket.status = Ticket.Status.OPEN
    ticket.save()
    with pytest.raises(TicketPermissionDenied):
        transition_ticket(
            ticket=ticket, target_status=Ticket.Status.CANCELLED, actor=other_requester
        )


@pytest.mark.django_db
def test_requester_cannot_be_assignee(ticket, agent, requester):
    with pytest.raises(InvalidAssignee):
        assign_ticket(ticket=ticket, assignee=requester, actor=agent)


@pytest.mark.django_db
def test_requester_cannot_assign(ticket, requester, agent):
    with pytest.raises(TicketPermissionDenied):
        assign_ticket(ticket=ticket, assignee=agent, actor=requester)


@pytest.mark.django_db
def test_agent_cannot_take_ticket_owned_by_another_agent(ticket, agent, user_factory):
    other_agent = user_factory(email="second-agent@example.com", role=User.Role.AGENT)
    ticket.assignee = other_agent
    ticket.save()
    with pytest.raises(TicketAlreadyAssigned):
        take_ownership(ticket=ticket, actor=agent)


@pytest.mark.django_db
def test_admin_can_reassign_ticket(ticket, agent, admin_user, user_factory):
    other_agent = user_factory(email="second-agent@example.com", role=User.Role.AGENT)
    ticket.assignee = agent
    ticket.save()
    ticket = assign_ticket(ticket=ticket, assignee=other_agent, actor=admin_user)
    assert ticket.assignee == other_agent


@pytest.mark.django_db
def test_update_records_field_history(ticket, requester):
    ticket = update_ticket(
        ticket=ticket,
        actor=requester,
        data={"priority": Ticket.Priority.URGENT, "title": "Critical printer"},
    )
    assert ticket.priority == Ticket.Priority.URGENT
    assert ticket.history.filter(field="priority").exists()
    assert ticket.history.filter(field="title").exists()


@pytest.mark.django_db
def test_requester_cannot_edit_non_open_ticket(ticket, requester):
    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save()
    with pytest.raises(TicketPermissionDenied):
        update_ticket(ticket=ticket, actor=requester, data={"title": "Changed"})
