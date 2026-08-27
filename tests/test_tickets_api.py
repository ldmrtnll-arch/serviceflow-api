import pytest
from django.urls import reverse

from apps.tickets.models import Ticket, TicketComment, TicketHistory


def ticket_url(ticket, action=None):
    name = f"ticket-{action or 'detail'}"
    return reverse(name, kwargs={"public_id": ticket.public_id})


@pytest.mark.django_db
def test_requester_list_and_retrieve_are_isolated(
    api_client, requester, other_requester, category, ticket
):
    other = Ticket.objects.create(
        requester=other_requester, category=category, title="Secret", description="Hidden"
    )
    api_client.force_authenticate(requester)
    response = api_client.get(reverse("ticket-list"))
    assert response.status_code == 200
    assert [row["id"] for row in response.data["results"]] == [str(ticket.public_id)]
    assert api_client.get(ticket_url(other)).status_code == 404


@pytest.mark.django_db
def test_agent_can_list_all_tickets(api_client, agent, ticket, other_requester, category):
    Ticket.objects.create(
        requester=other_requester, category=category, title="Another", description="Ticket"
    )
    api_client.force_authenticate(agent)
    assert api_client.get(reverse("ticket-list")).data["count"] == 2


@pytest.mark.django_db
def test_create_ignores_server_controlled_fields(api_client, requester, agent, category):
    api_client.force_authenticate(requester)
    response = api_client.post(
        reverse("ticket-list"),
        {
            "title": "Cannot log in",
            "description": "Account is locked",
            "category": category.pk,
            "status": "closed",
            "assignee": agent.pk,
        },
        format="json",
    )
    assert response.status_code == 201
    ticket = Ticket.objects.get(public_id=response.data["id"])
    assert ticket.status == Ticket.Status.OPEN
    assert ticket.assignee is None
    assert ticket.requester == requester


@pytest.mark.django_db
def test_patch_protects_workflow_fields(api_client, requester, ticket):
    api_client.force_authenticate(requester)
    response = api_client.patch(
        ticket_url(ticket), {"title": "Updated", "status": "closed"}, format="json"
    )
    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.title == "Updated"
    assert ticket.status == Ticket.Status.OPEN


@pytest.mark.django_db
def test_take_and_transition_actions(api_client, agent, ticket):
    api_client.force_authenticate(agent)
    take = api_client.post(ticket_url(ticket, "take"))
    assert take.status_code == 200
    assert take.data["assignee"]["id"] == agent.pk

    transition = api_client.post(
        ticket_url(ticket, "transition"), {"status": "in_progress"}, format="json"
    )
    assert transition.status_code == 200
    assert transition.data["status"] == "in_progress"


@pytest.mark.django_db
def test_requester_take_returns_structured_forbidden(api_client, requester, ticket):
    api_client.force_authenticate(requester)
    response = api_client.post(ticket_url(ticket, "take"))
    assert response.status_code == 403
    assert response.data["code"] == "permission_denied"


@pytest.mark.django_db
def test_invalid_transition_returns_structured_error(api_client, agent, ticket):
    api_client.force_authenticate(agent)
    response = api_client.post(
        ticket_url(ticket, "transition"), {"status": "closed"}, format="json"
    )
    assert response.status_code == 400
    assert response.data["code"] == "invalid_status_transition"


@pytest.mark.django_db
def test_comments_follow_ticket_access(api_client, requester, other_requester, ticket):
    api_client.force_authenticate(requester)
    created = api_client.post(
        ticket_url(ticket, "comments"), {"content": "More information"}, format="json"
    )
    assert created.status_code == 201
    assert TicketComment.objects.get().author == requester
    assert api_client.get(ticket_url(ticket, "comments")).data["count"] == 1

    api_client.force_authenticate(other_requester)
    assert api_client.get(ticket_url(ticket, "comments")).status_code == 404
    assert api_client.post(ticket_url(ticket, "comments"), {"content": "IDOR"}).status_code == 404


@pytest.mark.django_db
def test_history_is_read_only_and_scoped(api_client, requester, ticket):
    TicketHistory.objects.create(
        ticket=ticket, actor=requester, action=TicketHistory.Action.CREATED
    )
    api_client.force_authenticate(requester)
    response = api_client.get(ticket_url(ticket, "history"))
    assert response.status_code == 200
    assert response.data["results"][0]["action"] == "created"
    assert api_client.post(ticket_url(ticket, "history"), {}).status_code == 405


@pytest.mark.django_db
def test_filter_search_ordering_and_pagination(api_client, agent, ticket, category, requester):
    Ticket.objects.create(
        requester=requester,
        category=category,
        title="Network outage",
        description="Router down",
        priority=Ticket.Priority.URGENT,
    )
    api_client.force_authenticate(agent)
    response = api_client.get(
        reverse("ticket-list"), {"priority": "urgent", "search": "router", "page_size": 1}
    )
    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["priority"] == "urgent"


@pytest.mark.django_db
def test_categories_are_read_only_except_for_admin(api_client, requester, admin_user):
    api_client.force_authenticate(requester)
    assert (
        api_client.post(reverse("category-list"), {"name": "New", "slug": "new"}).status_code == 403
    )

    api_client.force_authenticate(admin_user)
    response = api_client.post(
        reverse("category-list"), {"name": "New", "slug": "new"}, format="json"
    )
    assert response.status_code == 201


@pytest.mark.django_db
def test_health_and_private_ticket_endpoint(api_client):
    assert api_client.get(reverse("health")).status_code == 200
    assert api_client.get(reverse("ticket-list")).status_code == 401
