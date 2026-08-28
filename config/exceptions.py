import logging

from django.conf import settings
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.tickets.exceptions import TicketDomainError

logger = logging.getLogger("serviceflow.exceptions")


def api_exception_handler(exc, context):
    if isinstance(exc, TicketDomainError):
        return Response({"code": exc.code, "detail": str(exc)}, status=exc.status_code)
    response = exception_handler(exc, context)
    if response is None:
        logger.error(
            "unhandled_api_exception",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        if settings.DEBUG:
            return None
        return Response(
            {"code": "internal_error", "detail": "An unexpected error occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, exceptions.ValidationError):
        return Response(
            {
                "code": "validation_error",
                "detail": "The submitted data is invalid.",
                "errors": response.data,
            },
            status=response.status_code,
            headers=response.headers,
        )

    codes = {
        status.HTTP_401_UNAUTHORIZED: "not_authenticated",
        status.HTTP_403_FORBIDDEN: "permission_denied",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        status.HTTP_429_TOO_MANY_REQUESTS: "throttled",
    }
    detail = response.data.get("detail", "Request failed.")
    return Response(
        {"code": codes.get(response.status_code, f"http_{response.status_code}"), "detail": detail},
        status=response.status_code,
        headers=response.headers,
    )
