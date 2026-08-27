from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, SLAPolicyViewSet, TicketMetricsView, TicketViewSet

router = DefaultRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("categories", CategoryViewSet, basename="category")
router.register("sla-policies", SLAPolicyViewSet, basename="sla-policy")

urlpatterns = [path("metrics/", TicketMetricsView.as_view(), name="ticket-metrics"), *router.urls]
