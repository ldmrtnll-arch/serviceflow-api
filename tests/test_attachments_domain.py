import hashlib

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError

from apps.tickets.attachments import delete_attachment, upload_attachment, validate_attachment
from apps.tickets.exceptions import (
    AttachmentNotAllowed,
    AttachmentPermissionDenied,
    AttachmentStorageError,
    InvalidAttachment,
)
from apps.tickets.models import Ticket, TicketAttachment, TicketHistory


def upload(name="report.pdf", content=b"valid document", content_type="application/pdf"):
    return SimpleUploadedFile(name, content, content_type=content_type)


@pytest.mark.django_db
def test_validation_hashes_in_chunks_and_rewinds_file():
    file = upload("relatório final.pdf", b"hello")
    validated = validate_attachment(file)
    assert validated.original_name == "relatório final.pdf"
    assert validated.sha256 == hashlib.sha256(b"hello").hexdigest()
    assert file.read() == b"hello"


@pytest.mark.parametrize(
    ("name", "content", "content_type"),
    [
        ("virus.exe", b"MZ", "application/pdf"),
        ("vector.svg", b"<svg/>", "image/svg+xml"),
        ("page.html", b"<html/>", "text/html"),
        ("no-extension", b"text", "text/plain"),
        ("empty.txt", b"", "text/plain"),
        ("mismatch.png", b"image", "application/pdf"),
        ("bad\r\nname.pdf", b"pdf", "application/pdf"),
        ("a" * 256 + ".pdf", b"pdf", "application/pdf"),
    ],
)
def test_validation_rejects_unsafe_files(name, content, content_type):
    with pytest.raises(InvalidAttachment):
        validate_attachment(upload(name, content, content_type))


def test_validation_rejects_oversized_file(settings):
    settings.MAX_ATTACHMENT_SIZE_BYTES = 3
    with pytest.raises(InvalidAttachment, match="exceeds"):
        validate_attachment(upload(content=b"four"))


@pytest.mark.django_db
def test_upload_stores_metadata_content_and_history(ticket, requester, fake_storage):
    attachment = upload_attachment(
        ticket=ticket,
        uploaded_by=requester,
        uploaded_file=upload("../../safe.pdf", b"content"),
        storage=fake_storage,
    )
    assert attachment.original_name == "safe.pdf"
    assert attachment.storage_key == f"tickets/{ticket.public_id}/{attachment.public_id}"
    assert attachment.storage_key in fake_storage.objects
    assert fake_storage.objects[attachment.storage_key]["content"] == b"content"
    history = ticket.history.get(action=TicketHistory.Action.ATTACHMENT_UPLOADED)
    assert str(attachment.public_id) in history.new_value
    assert "safe.pdf" in history.new_value


@pytest.mark.django_db
def test_duplicate_names_and_content_are_allowed(ticket, requester, fake_storage):
    first = upload_attachment(
        ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
    )
    second = upload_attachment(
        ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
    )
    assert first.storage_key != second.storage_key
    assert first.sha256 == second.sha256


@pytest.mark.django_db
@pytest.mark.parametrize("status", [Ticket.Status.CLOSED, Ticket.Status.CANCELLED])
def test_terminal_ticket_rejects_upload_before_storage(ticket, requester, fake_storage, status):
    ticket.status = status
    ticket.save()
    with pytest.raises(AttachmentNotAllowed):
        upload_attachment(
            ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
        )
    assert not fake_storage.objects


@pytest.mark.django_db
def test_storage_failure_does_not_create_metadata(ticket, requester, fake_storage):
    fake_storage.upload_error = AttachmentStorageError("Unavailable")
    with pytest.raises(AttachmentStorageError):
        upload_attachment(
            ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
        )
    assert not TicketAttachment.objects.exists()


@pytest.mark.django_db
def test_database_failure_triggers_compensating_delete(
    ticket, requester, fake_storage, monkeypatch
):
    monkeypatch.setattr(
        "apps.tickets.attachments.TicketAttachment.objects.create",
        lambda **kwargs: (_ for _ in ()).throw(IntegrityError("database failed")),
    )
    with pytest.raises(IntegrityError):
        upload_attachment(
            ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
        )
    assert len(fake_storage.deleted) == 1
    assert not fake_storage.objects


@pytest.mark.django_db
def test_terminal_race_after_upload_cleans_object(ticket, requester, fake_storage):
    def close_ticket():
        Ticket.objects.filter(pk=ticket.pk).update(status=Ticket.Status.CLOSED)

    fake_storage.on_upload = close_ticket
    with pytest.raises(AttachmentNotAllowed):
        upload_attachment(
            ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
        )
    assert len(fake_storage.deleted) == 1
    assert not TicketAttachment.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_requester_deletes_own_attachment_after_commit(ticket, requester, fake_storage):
    attachment = upload_attachment(
        ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
    )
    delete_attachment(ticket=ticket, attachment=attachment, actor=requester, storage=fake_storage)
    assert not TicketAttachment.objects.filter(pk=attachment.pk).exists()
    assert attachment.storage_key in fake_storage.deleted
    history = ticket.history.get(action=TicketHistory.Action.ATTACHMENT_DELETED)
    assert "report.pdf" in history.old_value
    assert str(attachment.public_id) in history.new_value


@pytest.mark.django_db
def test_requester_cannot_delete_another_users_attachment(
    ticket, requester, other_requester, fake_storage
):
    attachment = upload_attachment(
        ticket=ticket, uploaded_by=other_requester, uploaded_file=upload(), storage=fake_storage
    )
    with pytest.raises(AttachmentPermissionDenied):
        delete_attachment(
            ticket=ticket, attachment=attachment, actor=requester, storage=fake_storage
        )


@pytest.mark.django_db
def test_terminal_ticket_preserves_attachment(ticket, requester, fake_storage):
    attachment = upload_attachment(
        ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
    )
    ticket.status = Ticket.Status.CANCELLED
    ticket.save()
    with pytest.raises(AttachmentNotAllowed):
        delete_attachment(
            ticket=ticket, attachment=attachment, actor=requester, storage=fake_storage
        )
    assert TicketAttachment.objects.filter(pk=attachment.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_delete_storage_failure_keeps_committed_audit_and_removed_metadata(
    ticket, requester, fake_storage
):
    attachment = upload_attachment(
        ticket=ticket, uploaded_by=requester, uploaded_file=upload(), storage=fake_storage
    )
    fake_storage.delete_error = AttachmentStorageError("Unavailable")
    delete_attachment(ticket=ticket, attachment=attachment, actor=requester, storage=fake_storage)
    assert not TicketAttachment.objects.filter(pk=attachment.pk).exists()
    assert ticket.history.filter(action=TicketHistory.Action.ATTACHMENT_DELETED).count() == 1
