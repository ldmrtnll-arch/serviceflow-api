from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User

from .filters import TicketFilter
from .models import SLAPolicy, Ticket, TicketCategory
from .permissions import IsAdminOrReadOnly, IsOperator, SLAPolicyPermission
from .serializers import (
    CategorySerializer,
    SLAPolicySerializer,
    TicketAssignmentSerializer,
    TicketCommentSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketHistorySerializer,
    TicketListSerializer,
    TicketTransitionSerializer,
    TicketUpdateSerializer,
)
from .services import (
    add_ticket_comment,
    assign_ticket,
    create_ticket,
    take_ownership,
    transition_ticket,
    update_ticket,
)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = TicketCategory.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"
    search_fields = ("name", "description")
    ordering_fields = ("name", "created_at")
    http_method_names = ("get", "post", "patch", "head", "options")


class SLAPolicyViewSet(viewsets.ModelViewSet):
    queryset = SLAPolicy.objects.all()
    serializer_class = SLAPolicySerializer
    permission_classes = [SLAPolicyPermission]
    filterset_fields = ("priority", "is_active")
    ordering_fields = ("priority", "created_at")
    http_method_names = ("get", "post", "patch", "head", "options")


class TicketViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Ticket.objects.all()
    lookup_field = "public_id"
    lookup_url_kwarg = "public_id"
    filterset_class = TicketFilter
    search_fields = ("title", "description")
    ordering_fields = ("created_at", "updated_at", "priority", "status")

    def get_queryset(self) -> QuerySet[Ticket]:
        queryset = Ticket.objects.select_related("requester", "assignee", "category")
        if getattr(self, "swagger_fake_view", False):
            return queryset.none()
        if self.request.user.role == User.Role.REQUESTER:
            queryset = queryset.filter(requester=self.request.user)
        return queryset

    def get_serializer_class(self):
        return {
            "list": TicketListSerializer,
            "create": TicketCreateSerializer,
            "partial_update": TicketUpdateSerializer,
            "update": TicketUpdateSerializer,
        }.get(self.action, TicketDetailSerializer)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = create_ticket(requester=request.user, **serializer.validated_data)
        return Response(
            TicketDetailSerializer(ticket, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        if not kwargs.get("partial", False):
            return Response(
                {"detail": "Use PATCH for ticket updates."},
                status=status.HTTP_405_METHOD_NOT_ALLOWED,
            )
        ticket = self.get_object()
        serializer = self.get_serializer(ticket, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        ticket = update_ticket(ticket=ticket, actor=request.user, data=serializer.validated_data)
        return Response(TicketDetailSerializer(ticket).data)

    @extend_schema(request=None, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def take(self, request, **kwargs):
        ticket = take_ownership(ticket=self.get_object(), actor=request.user)
        return Response(TicketDetailSerializer(ticket).data)

    @extend_schema(request=TicketAssignmentSerializer, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def assign(self, request, **kwargs):
        serializer = TicketAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = assign_ticket(
            ticket=self.get_object(), actor=request.user, **serializer.validated_data
        )
        return Response(TicketDetailSerializer(ticket).data)

    @extend_schema(request=TicketTransitionSerializer, responses=TicketDetailSerializer)
    @action(detail=True, methods=["post"])
    def transition(self, request, **kwargs):
        serializer = TicketTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = transition_ticket(
            ticket=self.get_object(),
            target_status=serializer.validated_data["status"],
            actor=request.user,
        )
        return Response(TicketDetailSerializer(ticket).data)

    @extend_schema(responses=TicketCommentSerializer(many=True))
    @action(detail=True, methods=["get", "post"])
    def comments(self, request, **kwargs):
        ticket = self.get_object()
        if request.method == "POST":
            serializer = TicketCommentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            comment = add_ticket_comment(
                ticket=ticket, author=request.user, content=serializer.validated_data["content"]
            )
            return Response(TicketCommentSerializer(comment).data, status=status.HTTP_201_CREATED)
        comments = ticket.comments.select_related("author")
        page = self.paginate_queryset(comments)
        serializer = TicketCommentSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(responses=TicketHistorySerializer(many=True))
    @action(detail=True, methods=["get"])
    def history(self, request, **kwargs):
        entries = self.get_object().history.select_related("actor")
        page = self.paginate_queryset(entries)
        serializer = TicketHistorySerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


class TicketMetricsView(APIView):
    permission_classes = [IsOperator]

    @extend_schema(responses=dict)
    def get(self, request):
        response_time = ExpressionWrapper(
            F("first_responded_at") - F("created_at"), output_field=DurationField()
        )
        resolution_time = ExpressionWrapper(
            F("first_resolved_at") - F("created_at"), output_field=DurationField()
        )
        metrics = Ticket.objects.aggregate(
            total=Count("id"),
            open=Count("id", filter=Q(status=Ticket.Status.OPEN)),
            in_progress=Count("id", filter=Q(status=Ticket.Status.IN_PROGRESS)),
            waiting_requester=Count("id", filter=Q(status=Ticket.Status.WAITING_REQUESTER)),
            resolved=Count("id", filter=Q(status=Ticket.Status.RESOLVED)),
            closed=Count("id", filter=Q(status=Ticket.Status.CLOSED)),
            cancelled=Count("id", filter=Q(status=Ticket.Status.CANCELLED)),
            first_response_breached=Count(
                "id", filter=Q(sla_first_response_breached_at__isnull=False)
            ),
            resolution_breached=Count("id", filter=Q(sla_resolution_breached_at__isnull=False)),
            average_first_response=Avg(response_time),
            average_resolution=Avg(resolution_time),
        )
        first_average = metrics.pop("average_first_response")
        resolution_average = metrics.pop("average_resolution")
        metrics["sla"] = {
            "first_response_breached": metrics.pop("first_response_breached"),
            "resolution_breached": metrics.pop("resolution_breached"),
            "average_first_response_seconds": (
                first_average.total_seconds() if first_average else None
            ),
            "average_resolution_seconds": (
                resolution_average.total_seconds() if resolution_average else None
            ),
        }
        return Response(metrics)
