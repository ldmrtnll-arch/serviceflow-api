import pytest
from django.urls import reverse

from apps.accounts.models import User


@pytest.mark.django_db
def test_public_registration_forces_requester_role(api_client):
    response = api_client.post(
        reverse("register"),
        {
            "email": "new@example.com",
            "password": "VeryStrongPassword123!",
            "first_name": "New",
            "last_name": "User",
            "role": "admin",
        },
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(email="new@example.com")
    assert user.role == User.Role.REQUESTER
    assert user.check_password("VeryStrongPassword123!")


@pytest.mark.django_db
def test_registration_rejects_duplicate_email(api_client, requester):
    response = api_client.post(
        reverse("register"),
        {
            "email": requester.email,
            "password": "VeryStrongPassword123!",
            "first_name": "Duplicate",
            "last_name": "User",
        },
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_login_refresh_and_me(api_client, requester):
    login = api_client.post(
        reverse("login"), {"email": requester.email, "password": "StrongPassword123!"}
    )
    assert login.status_code == 200
    assert {"access", "refresh"} <= login.data.keys()

    refresh = api_client.post(reverse("token-refresh"), {"refresh": login.data["refresh"]})
    assert refresh.status_code == 200

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
    me = api_client.get(reverse("me"))
    assert me.status_code == 200
    assert me.data["email"] == requester.email
    assert "password" not in me.data


@pytest.mark.django_db
def test_me_requires_authentication(api_client):
    assert api_client.get(reverse("me")).status_code == 401
