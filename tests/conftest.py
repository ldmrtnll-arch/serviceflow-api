import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.tickets.models import SLAPolicy, Ticket, TicketCategory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user_factory(db):
    def create(email="user@example.com", role=User.Role.REQUESTER, **kwargs):
        return User.objects.create_user(
            email=email,
            password="StrongPassword123!",
            first_name=kwargs.pop("first_name", "Test"),
            last_name=kwargs.pop("last_name", "User"),
            role=role,
            **kwargs,
        )

    return create


@pytest.fixture
def requester(user_factory):
    return user_factory()


@pytest.fixture
def other_requester(user_factory):
    return user_factory(email="other@example.com")


@pytest.fixture
def agent(user_factory):
    return user_factory(email="agent@example.com", role=User.Role.AGENT)


@pytest.fixture
def admin_user(user_factory):
    return user_factory(email="admin@example.com", role=User.Role.ADMIN, is_staff=True)


@pytest.fixture
def category(db):
    defaults = {
        Ticket.Priority.LOW: (1440, 7200),
        Ticket.Priority.MEDIUM: (480, 4320),
        Ticket.Priority.HIGH: (240, 1440),
        Ticket.Priority.URGENT: (60, 480),
    }
    for priority, (first_response, resolution) in defaults.items():
        SLAPolicy.objects.get_or_create(
            priority=priority,
            defaults={
                "name": f"Default {priority}",
                "first_response_minutes": first_response,
                "resolution_minutes": resolution,
            },
        )
    return TicketCategory.objects.create(name="Software", slug="software")


@pytest.fixture
def ticket(requester, category):
    return Ticket.objects.create(
        requester=requester,
        category=category,
        title="Printer is offline",
        description="The office printer cannot be reached.",
    )
