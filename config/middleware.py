import logging
import time

from django.conf import settings
from django.http import JsonResponse

from .observability import REQUEST_ID_HEADER, get_request_id, reset_request_id, set_request_id

logger = logging.getLogger("serviceflow.http")


class RequestObservabilityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.request_id = get_request_id()
        started = time.monotonic()
        try:
            try:
                response = self.get_response(request)
            except Exception:
                logger.exception("unhandled_http_exception")
                if settings.DEBUG:
                    raise
                response = JsonResponse(
                    {"code": "internal_error", "detail": "An unexpected error occurred."},
                    status=500,
                )
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            response[REQUEST_ID_HEADER] = request.request_id
            user = getattr(request, "user", None)
            extra = {
                "method": request.method,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "user_id": (
                    getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
                ),
            }
            event = (
                "slow_http_request"
                if duration_ms >= settings.SLOW_REQUEST_THRESHOLD_MS
                else "http_request"
            )
            (logger.warning if event == "slow_http_request" else logger.info)(event, extra=extra)
            return response
        finally:
            reset_request_id(token)
