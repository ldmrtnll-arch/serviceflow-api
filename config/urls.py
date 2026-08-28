import logging

from django.contrib import admin
from django.core.cache import cache
from django.db import connections
from django.urls import include, path
from drf_spectacular.utils import extend_schema, inline_serializer
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

logger = logging.getLogger("serviceflow.health")


@extend_schema(responses=inline_serializer("HealthResponse", {"status": serializers.CharField()}))
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@extend_schema(
    responses=inline_serializer(
        "ReadinessResponse",
        {"status": serializers.CharField(), "checks": serializers.DictField()},
    )
)
@api_view(["GET"])
@permission_classes([AllowAny])
def readiness(request):
    checks = {"database": "ok", "redis": "ok"}
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("readiness_database_unavailable")
        checks["database"] = "unavailable"
        return Response({"status": "unavailable", "checks": checks}, status=503)

    try:
        cache.set("serviceflow:readiness", "ok", timeout=5)
        if cache.get("serviceflow:readiness") != "ok":
            checks["redis"] = "unavailable"
            logger.warning("readiness_redis_unavailable")
    except Exception:
        checks["redis"] = "unavailable"
        logger.exception("readiness_redis_unavailable")
    status_value = "degraded" if checks["redis"] != "ok" else "ready"
    return Response({"status": status_value, "checks": checks})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("health/ready/", readiness, name="readiness"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.tickets.urls")),
]
