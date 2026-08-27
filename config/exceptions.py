from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.tickets.exceptions import TicketDomainError


def api_exception_handler(exc, context):
    if isinstance(exc, TicketDomainError):
        return Response({"code": exc.code, "detail": str(exc)}, status=exc.status_code)
    return exception_handler(exc, context)
