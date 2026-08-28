from django.contrib import admin

from .models import (
    SLAPolicy,
    Ticket,
    TicketAttachment,
    TicketCategory,
    TicketComment,
    TicketHistory,
)


@admin.register(TicketCategory)
class TicketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(SLAPolicy)
class SLAPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "priority",
        "first_response_minutes",
        "resolution_minutes",
        "is_active",
    )
    list_filter = ("priority", "is_active")
    search_fields = ("name",)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("public_id", "title", "status", "priority", "requester", "assignee")
    list_filter = ("status", "priority", "category")
    search_fields = ("public_id", "title", "description", "requester__email")
    readonly_fields = (
        "public_id",
        "created_at",
        "updated_at",
        "resolved_at",
        "first_resolved_at",
        "closed_at",
        "first_response_due_at",
        "resolution_due_at",
        "first_responded_at",
        "sla_first_response_breached_at",
        "sla_resolution_breached_at",
    )
    list_select_related = ("requester", "assignee", "category")


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "created_at")
    search_fields = ("content", "author__email", "ticket__title")
    list_select_related = ("ticket", "author")


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "original_name",
        "ticket",
        "uploaded_by",
        "size_bytes",
        "created_at",
    )
    search_fields = ("public_id", "original_name", "sha256", "ticket__title", "uploaded_by__email")
    list_filter = ("content_type", "created_at")
    list_select_related = ("ticket", "uploaded_by")
    readonly_fields = (
        "public_id",
        "ticket",
        "uploaded_by",
        "original_name",
        "storage_key",
        "content_type",
        "size_bytes",
        "sha256",
        "created_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(TicketHistory)
class TicketHistoryAdmin(admin.ModelAdmin):
    list_display = ("ticket", "action", "field", "actor", "created_at")
    list_filter = ("action", "field")
    search_fields = ("ticket__title", "actor__email")
    readonly_fields = ("ticket", "actor", "action", "field", "old_value", "new_value", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
