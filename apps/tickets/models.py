import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class TicketPriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class TicketCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "ticket categories"

    def __str__(self):
        return self.name


class SLAPolicy(models.Model):
    name = models.CharField(max_length=100)
    priority = models.CharField(max_length=10, choices=TicketPriority)
    first_response_minutes = models.PositiveIntegerField()
    resolution_minutes = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("priority", "name")
        constraints = [
            models.CheckConstraint(
                condition=Q(first_response_minutes__gt=0), name="sla_first_response_positive"
            ),
            models.CheckConstraint(
                condition=Q(resolution_minutes__gt=0), name="sla_resolution_positive"
            ),
            models.CheckConstraint(
                condition=Q(resolution_minutes__gte=models.F("first_response_minutes")),
                name="sla_resolution_after_response",
            ),
            models.UniqueConstraint(
                fields=("priority",),
                condition=Q(is_active=True),
                name="unique_active_sla_per_priority",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.priority})"

    def clean(self):
        super().clean()
        errors = {}
        if self.first_response_minutes is not None and self.first_response_minutes <= 0:
            errors["first_response_minutes"] = "Must be greater than zero."
        if self.resolution_minutes is not None and self.resolution_minutes <= 0:
            errors["resolution_minutes"] = "Must be greater than zero."
        if (
            self.first_response_minutes is not None
            and self.resolution_minutes is not None
            and self.resolution_minutes < self.first_response_minutes
        ):
            errors["resolution_minutes"] = "Must be at least the first response time."
        if errors:
            raise ValidationError(errors)


class Ticket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING_REQUESTER = "waiting_requester", "Waiting for requester"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"
        CANCELLED = "cancelled", "Cancelled"

    Priority = TicketPriority

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=30, choices=Status, default=Status.OPEN, db_index=True)
    priority = models.CharField(
        max_length=10, choices=Priority, default=Priority.MEDIUM, db_index=True
    )
    category = models.ForeignKey(TicketCategory, on_delete=models.PROTECT, related_name="tickets")
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_tickets"
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assigned_tickets",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    first_resolved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    first_response_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolution_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    first_responded_at = models.DateTimeField(null=True, blank=True)
    sla_first_response_breached_at = models.DateTimeField(null=True, blank=True)
    sla_resolution_breached_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status", "-created_at"), name="ticket_status_created_idx"),
            models.Index(fields=("priority", "-created_at"), name="ticket_priority_created_idx"),
        ]

    def __str__(self):
        return f"{self.public_id}: {self.title}"

    @property
    def first_response_sla_status(self):
        return self._sla_status(
            completed_at=self.first_responded_at,
            due_at=self.first_response_due_at,
            breached_at=self.sla_first_response_breached_at,
        )

    @property
    def resolution_sla_status(self):
        return self._sla_status(
            completed_at=self.first_resolved_at,
            due_at=self.resolution_due_at,
            breached_at=self.sla_resolution_breached_at,
        )

    def _sla_status(self, *, completed_at, due_at, breached_at):
        if breached_at or (completed_at and due_at and completed_at > due_at):
            return "breached"
        if completed_at:
            return "met"
        if not due_at or self.status == self.Status.CANCELLED:
            return "not_applicable"
        if timezone.now() > due_at:
            return "breached"
        return "pending"


class TicketComment(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ticket_comments"
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Comment by {self.author} on {self.ticket.public_id}"


class TicketAttachment(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ticket_attachments",
    )
    original_name = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=255, unique=True)
    content_type = models.CharField(max_length=150)
    size_bytes = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.original_name} on {self.ticket.public_id}"


class TicketHistory(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "Created"
        STATUS_CHANGED = "status_changed", "Status changed"
        PRIORITY_CHANGED = "priority_changed", "Priority changed"
        CATEGORY_CHANGED = "category_changed", "Category changed"
        ASSIGNED = "assigned", "Assigned"
        UNASSIGNED = "unassigned", "Unassigned"
        UPDATED = "updated", "Updated"
        SLA_FIRST_RESPONSE_COMPLETED = (
            "sla_first_response_completed",
            "SLA first response completed",
        )
        SLA_RESOLUTION_COMPLETED = "sla_resolution_completed", "SLA resolution completed"
        SLA_FIRST_RESPONSE_BREACHED = (
            "sla_first_response_breached",
            "SLA first response breached",
        )
        SLA_RESOLUTION_BREACHED = "sla_resolution_breached", "SLA resolution breached"
        ATTACHMENT_UPLOADED = "attachment_uploaded", "Attachment uploaded"
        ATTACHMENT_DELETED = "attachment_deleted", "Attachment deleted"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="history")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="ticket_history_entries",
        null=True,
    )
    action = models.CharField(max_length=30, choices=Action)
    field = models.CharField(max_length=50, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.action} on {self.ticket.public_id}"
