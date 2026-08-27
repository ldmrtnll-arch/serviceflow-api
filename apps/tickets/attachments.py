import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

from django.conf import settings
from django.db import transaction

from apps.accounts.models import User

from .exceptions import (
    AttachmentNotAllowed,
    AttachmentPermissionDenied,
    AttachmentStorageError,
    InvalidAttachment,
)
from .models import Ticket, TicketAttachment, TicketHistory

logger = logging.getLogger(__name__)

ALLOWED_FILE_TYPES = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}
TERMINAL_STATUSES = {Ticket.Status.CLOSED, Ticket.Status.CANCELLED}
MAX_FILENAME_LENGTH = 200


@dataclass(frozen=True)
class ValidatedUpload:
    original_name: str
    content_type: str
    size_bytes: int
    sha256: str


def validate_attachment(uploaded_file) -> ValidatedUpload:
    raw_name = str(uploaded_file.name or "")
    if "\r" in raw_name or "\n" in raw_name:
        raise InvalidAttachment("Filename contains invalid control characters.")
    original_name = PurePosixPath(raw_name.replace("\\", "/")).name.strip()
    if not original_name or len(original_name) > MAX_FILENAME_LENGTH:
        raise InvalidAttachment(
            f"Filename must contain between 1 and {MAX_FILENAME_LENGTH} characters."
        )
    extension = PurePosixPath(original_name).suffix.lower()
    content_type = str(uploaded_file.content_type or "").split(";", 1)[0].strip().lower()
    if extension not in ALLOWED_FILE_TYPES or content_type not in ALLOWED_FILE_TYPES[extension]:
        raise InvalidAttachment("File extension and content type are not allowed.")
    size = int(uploaded_file.size or 0)
    if size <= 0:
        raise InvalidAttachment("Empty files are not allowed.")
    if size > settings.MAX_ATTACHMENT_SIZE_BYTES:
        raise InvalidAttachment(
            f"File exceeds the {settings.MAX_ATTACHMENT_SIZE_BYTES} byte limit."
        )
    digest = hashlib.sha256()
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return ValidatedUpload(original_name, content_type, size, digest.hexdigest())


def _ensure_upload_allowed(ticket: Ticket) -> None:
    if ticket.status in TERMINAL_STATUSES:
        raise AttachmentNotAllowed("Attachments cannot be changed on terminal tickets.")


def _attachment_history(ticket, actor, action, attachment_id, filename, size_bytes):
    TicketHistory.objects.create(
        ticket=ticket,
        actor=actor,
        action=action,
        field="attachment",
        old_value="" if action == TicketHistory.Action.ATTACHMENT_UPLOADED else filename,
        new_value=(
            f"{attachment_id}|{filename}|{size_bytes}"
            if action == TicketHistory.Action.ATTACHMENT_UPLOADED
            else str(attachment_id)
        ),
    )


def upload_attachment(*, ticket: Ticket, uploaded_by: User, uploaded_file, storage):
    _ensure_upload_allowed(ticket)
    validated = validate_attachment(uploaded_file)
    attachment_id = uuid.uuid4()
    storage_key = f"tickets/{ticket.public_id}/{attachment_id}"
    storage.upload(key=storage_key, file_obj=uploaded_file, content_type=validated.content_type)
    try:
        with transaction.atomic():
            locked_ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
            _ensure_upload_allowed(locked_ticket)
            attachment = TicketAttachment.objects.create(
                public_id=attachment_id,
                ticket=locked_ticket,
                uploaded_by=uploaded_by,
                original_name=validated.original_name,
                storage_key=storage_key,
                content_type=validated.content_type,
                size_bytes=validated.size_bytes,
                sha256=validated.sha256,
            )
            _attachment_history(
                locked_ticket,
                uploaded_by,
                TicketHistory.Action.ATTACHMENT_UPLOADED,
                attachment.public_id,
                attachment.original_name,
                attachment.size_bytes,
            )
    except Exception:
        try:
            storage.delete(key=storage_key)
        except AttachmentStorageError:
            logger.exception("attachment_compensating_cleanup_failed key=%s", storage_key)
        raise
    return attachment


def delete_attachment(*, ticket: Ticket, attachment: TicketAttachment, actor: User, storage):
    with transaction.atomic():
        locked_ticket = Ticket.objects.select_for_update().get(pk=ticket.pk)
        _ensure_upload_allowed(locked_ticket)
        locked_attachment = TicketAttachment.objects.select_for_update().get(
            pk=attachment.pk, ticket=locked_ticket
        )
        if actor.role == User.Role.REQUESTER and locked_attachment.uploaded_by_id != actor.pk:
            raise AttachmentPermissionDenied("Requester may only delete their own attachment.")
        storage_key = locked_attachment.storage_key
        _attachment_history(
            locked_ticket,
            actor,
            TicketHistory.Action.ATTACHMENT_DELETED,
            locked_attachment.public_id,
            locked_attachment.original_name,
            locked_attachment.size_bytes,
        )
        locked_attachment.delete()

        def delete_object_after_commit():
            try:
                storage.delete(key=storage_key)
            except AttachmentStorageError:
                logger.exception("attachment_orphaned_object key=%s", storage_key)

        transaction.on_commit(delete_object_after_commit)
