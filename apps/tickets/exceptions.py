from rest_framework import status


class TicketDomainError(Exception):
    code = "ticket_domain_error"
    status_code = status.HTTP_400_BAD_REQUEST


class InvalidTicketTransition(TicketDomainError):
    code = "invalid_status_transition"


class InvalidAssignee(TicketDomainError):
    code = "invalid_assignee"


class TicketAlreadyAssigned(TicketDomainError):
    code = "ticket_already_assigned"
    status_code = status.HTTP_409_CONFLICT


class TicketPermissionDenied(TicketDomainError):
    code = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN


class SLAPolicyNotConfigured(TicketDomainError):
    code = "sla_policy_not_configured"
    status_code = status.HTTP_409_CONFLICT
