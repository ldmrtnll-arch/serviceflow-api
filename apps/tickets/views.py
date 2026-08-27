from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User

from .filters import TicketFilter
from .models import Ticket, TicketCategory
from .permissions import IsAdminOrReadOnly
from .serializers import (
    CategorySerializer,
    TicketAssignmentSerializer,
    TicketCommentSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    TicketHistorySerializer,
    TicketListSerializer,
    TicketTransitionSerializer,
    TicketUpdateSerializer,
)
from .services import assign_ticket, create_ticket, take_ownership, transition_ticket, update_ticket


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = TicketCategory.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = "slug"
    search_fields = ("name", "description")
    ordering_fields = ("name", "created_at")
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
            serializer.save(ticket=ticket, author=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
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
