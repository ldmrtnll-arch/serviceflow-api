import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.tickets.models import SLAPolicy, Ticket, TicketCategory
from apps.tickets.object_storage import PresignedDownload


@pytest.fixture
def api_client():
    return APIClient()


class FakeObjectStorage:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.upload_error = None
        self.delete_error = None
        self.on_upload = None

    def upload(self, *, key, file_obj, content_type):
        if self.upload_error:
            raise self.upload_error
        self.objects[key] = {"content": file_obj.read(), "content_type": content_type}
        file_obj.seek(0)
        if self.on_upload:
            self.on_upload()

    def delete(self, *, key):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(key)
        self.objects.pop(key, None)

    def generate_download_url(self, *, key, filename):
        return PresignedDownload(
            url=f"http://storage.local/{key}?filename={filename}", expires_in=300
        )


@pytest.fixture
def fake_storage():
    return FakeObjectStorage()


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
