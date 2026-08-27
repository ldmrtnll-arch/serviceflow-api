from rest_framework.routers import DefaultRouter

from .views import CategoryViewSet, TicketViewSet

router = DefaultRouter()
router.register("tickets", TicketViewSet, basename="ticket")
router.register("categories", CategoryViewSet, basename="category")

urlpatterns = router.urls
