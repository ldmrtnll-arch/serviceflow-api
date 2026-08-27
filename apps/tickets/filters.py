import django_filters
from django.db.models import Q
from django.utils import timezone

from .models import Ticket


class TicketFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(field_name="category__slug")
    assignee = django_filters.NumberFilter(field_name="assignee_id")
    requester = django_filters.NumberFilter(field_name="requester_id")
    sla_status = django_filters.CharFilter(method="filter_sla_status")
    overdue = django_filters.BooleanFilter(method="filter_overdue")

    class Meta:
        model = Ticket
        fields = (
            "status",
            "priority",
            "category",
            "assignee",
            "requester",
            "sla_status",
            "overdue",
        )

    def filter_sla_status(self, queryset, name, value):
        if value != "breached":
            return queryset
        now = timezone.now()
        return queryset.exclude(status=Ticket.Status.CANCELLED).filter(
            Q(sla_first_response_breached_at__isnull=False)
            | Q(sla_resolution_breached_at__isnull=False)
            | Q(first_responded_at__isnull=True, first_response_due_at__lt=now)
            | Q(first_resolved_at__isnull=True, resolution_due_at__lt=now)
        )

    def filter_overdue(self, queryset, name, value):
        if not value:
            return queryset
        return self.filter_sla_status(queryset, name, "breached")
