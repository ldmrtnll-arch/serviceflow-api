import hashlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.tickets.attachments import upload_attachment
from apps.tickets.exceptions import AttachmentStorageError
from apps.tickets.models import Ticket, TicketAttachment


def attachment_file(name="evidence.pdf", content=b"evidence", content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def attachments_url(ticket):
    return reverse("ticket-attachments", kwargs={"public_id": ticket.public_id})


def attachment_url(ticket, attachment, action="attachment-detail"):
    return reverse(
        f"ticket-{action}",
        kwargs={"public_id": ticket.public_id, "attachment_id": attachment.public_id},
    )


@pytest.fixture
def use_fake_storage(monkeypatch, fake_storage):
    monkeypatch.setattr("apps.tickets.views.get_object_storage", lambda: fake_storage)
    return fake_storage


@pytest.mark.django_db
def test_requester_uploads_lists_and_sees_attachment_count(
    api_client, requester, ticket, use_fake_storage
):
    api_client.force_authenticate(requester)
    response = api_client.post(
        attachments_url(ticket), {"file": attachment_file()}, format="multipart"
    )
    assert response.status_code == 201
    assert response.data["original_name"] == "evidence.pdf"
    assert response.data["sha256"] == hashlib.sha256(b"evidence").hexdigest()
    assert "storage_key" not in response.data
    assert "url" not in response.data

    listed = api_client.get(attachments_url(ticket))
    assert listed.status_code == 200
    assert listed.data["count"] == 1
    detail = api_client.get(reverse("ticket-detail", kwargs={"public_id": ticket.public_id}))
    assert detail.data["attachment_count"] == 1


@pytest.mark.django_db
def test_duplicate_filename_uploads_have_distinct_ids(
    api_client, requester, ticket, use_fake_storage
):
    api_client.force_authenticate(requester)
    first = api_client.post(
        attachments_url(ticket), {"file": attachment_file()}, format="multipart"
    )
    second = api_client.post(
        attachments_url(ticket), {"file": attachment_file()}, format="multipart"
    )
    assert first.status_code == second.status_code == 201
    assert first.data["id"] != second.data["id"]


@pytest.mark.django_db
def test_upload_validation_error_is_structured(api_client, requester, ticket, use_fake_storage):
    api_client.force_authenticate(requester)
    response = api_client.post(
        attachments_url(ticket),
        {"file": attachment_file("payload.exe", b"MZ", "application/pdf")},
        format="multipart",
    )
    assert response.status_code == 400
    assert response.data["code"] == "invalid_attachment"


@pytest.mark.django_db
def test_storage_failure_returns_503_without_metadata(
    api_client, requester, ticket, use_fake_storage
):
    use_fake_storage.upload_error = AttachmentStorageError("Unavailable")
    api_client.force_authenticate(requester)
    response = api_client.post(
        attachments_url(ticket), {"file": attachment_file()}, format="multipart"
    )
    assert response.status_code == 503
    assert response.data["code"] == "attachment_storage_unavailable"
    assert not TicketAttachment.objects.exists()


@pytest.mark.django_db
def test_download_returns_short_lived_presigned_url(
    api_client, requester, ticket, use_fake_storage
):
    attachment = upload_attachment(
        ticket=ticket,
        uploaded_by=requester,
        uploaded_file=attachment_file("report final.pdf"),
        storage=use_fake_storage,
    )
    api_client.force_authenticate(requester)
    response = api_client.get(attachment_url(ticket, attachment, "attachment-download"))
    assert response.status_code == 200
    assert response.data["expires_in"] == 300
    assert response.data["url"].startswith("http://storage.local/")


@pytest.mark.django_db
def test_requester_cannot_access_other_ticket_or_attachment(
    api_client,
    requester,
    other_requester,
    category,
    use_fake_storage,
):
    other_ticket = Ticket.objects.create(
        requester=other_requester, category=category, title="Private", description="Private"
    )
    attachment = upload_attachment(
        ticket=other_ticket,
        uploaded_by=other_requester,
        uploaded_file=attachment_file(),
        storage=use_fake_storage,
    )
    api_client.force_authenticate(requester)
    assert api_client.get(attachments_url(other_ticket)).status_code == 404
    assert (
        api_client.get(attachment_url(other_ticket, attachment, "attachment-download")).status_code
        == 404
    )
    assert api_client.delete(attachment_url(other_ticket, attachment)).status_code == 404


@pytest.mark.django_db
def test_attachment_must_belong_to_ticket_in_route(
    api_client, requester, other_requester, ticket, category, use_fake_storage
):
    other_ticket = Ticket.objects.create(
        requester=other_requester, category=category, title="Other", description="Other"
    )
    attachment = upload_attachment(
        ticket=other_ticket,
        uploaded_by=other_requester,
        uploaded_file=attachment_file(),
        storage=use_fake_storage,
    )
    api_client.force_authenticate(requester)
    wrong_url = reverse(
        "ticket-attachment-download",
        kwargs={"public_id": ticket.public_id, "attachment_id": attachment.public_id},
    )
    assert api_client.get(wrong_url).status_code == 404


@pytest.mark.django_db
def test_requester_deletes_own_attachment(api_client, requester, ticket, use_fake_storage):
    attachment = upload_attachment(
        ticket=ticket,
        uploaded_by=requester,
        uploaded_file=attachment_file(),
        storage=use_fake_storage,
    )
    api_client.force_authenticate(requester)
    response = api_client.delete(attachment_url(ticket, attachment))
    assert response.status_code == 204
    assert not TicketAttachment.objects.filter(pk=attachment.pk).exists()


@pytest.mark.django_db
def test_requester_cannot_delete_attachment_uploaded_by_agent(
    api_client, requester, agent, ticket, use_fake_storage
):
    attachment = upload_attachment(
        ticket=ticket,
        uploaded_by=agent,
        uploaded_file=attachment_file(),
        storage=use_fake_storage,
    )
    api_client.force_authenticate(requester)
    response = api_client.delete(attachment_url(ticket, attachment))
    assert response.status_code == 403


@pytest.mark.django_db
def test_agent_can_upload_and_delete_attachment(api_client, agent, ticket, use_fake_storage):
    api_client.force_authenticate(agent)
    created = api_client.post(
        attachments_url(ticket), {"file": attachment_file()}, format="multipart"
    )
    assert created.status_code == 201
    attachment = TicketAttachment.objects.get(public_id=created.data["id"])
    assert api_client.delete(attachment_url(ticket, attachment)).status_code == 204


@pytest.mark.django_db
@pytest.mark.parametrize("terminal_status", [Ticket.Status.CLOSED, Ticket.Status.CANCELLED])
def test_terminal_ticket_allows_read_but_blocks_changes(
    api_client, requester, ticket, use_fake_storage, terminal_status
):
    attachment = upload_attachment(
        ticket=ticket,
        uploaded_by=requester,
        uploaded_file=attachment_file(),
        storage=use_fake_storage,
    )
    ticket.status = terminal_status
    ticket.save()
    api_client.force_authenticate(requester)
    assert api_client.get(attachments_url(ticket)).status_code == 200
    assert (
        api_client.get(attachment_url(ticket, attachment, "attachment-download")).status_code == 200
    )
    assert (
        api_client.post(
            attachments_url(ticket), {"file": attachment_file()}, format="multipart"
        ).status_code
        == 409
    )
    assert api_client.delete(attachment_url(ticket, attachment)).status_code == 409


@pytest.mark.django_db
def test_attachment_endpoints_require_authentication(api_client, ticket):
    assert api_client.get(attachments_url(ticket)).status_code == 401
