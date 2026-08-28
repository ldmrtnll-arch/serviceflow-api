import logging

from django.core.cache import cache
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

logger = logging.getLogger(__name__)


class ResilientThrottleMixin:
    cache = cache

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.exception("throttle_cache_unavailable", extra={"path": request.path})
            return True


class ResilientAnonRateThrottle(ResilientThrottleMixin, AnonRateThrottle):
    pass


class ResilientUserRateThrottle(ResilientThrottleMixin, UserRateThrottle):
    pass


class LoginRateThrottle(ResilientAnonRateThrottle):
    scope = "login"


class RegisterRateThrottle(ResilientAnonRateThrottle):
    scope = "register"


class UploadRateThrottle(ResilientUserRateThrottle):
    scope = "upload"
