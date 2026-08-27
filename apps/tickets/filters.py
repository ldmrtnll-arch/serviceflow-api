import django_filters

from .models import Ticket


class TicketFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(field_name="category__slug")
    assignee = django_filters.NumberFilter(field_name="assignee_id")
    requester = django_filters.NumberFilter(field_name="requester_id")

    class Meta:
        model = Ticket
        fields = ("status", "priority", "category", "assignee", "requester")
