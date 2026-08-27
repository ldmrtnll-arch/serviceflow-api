from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import User

from .models import SLAPolicy, Ticket, TicketCategory, TicketComment, TicketHistory


class UserBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email", "first_name", "last_name")


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketCategory
        fields = ("id", "name", "slug", "description", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class CategoryBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketCategory
        fields = ("id", "name", "slug")


class SLAPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = SLAPolicy
        fields = (
            "id",
            "name",
            "priority",
            "first_response_minutes",
            "resolution_minutes",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate(self, attrs):
        first_response = attrs.get(
            "first_response_minutes", getattr(self.instance, "first_response_minutes", None)
        )
        resolution = attrs.get(
            "resolution_minutes", getattr(self.instance, "resolution_minutes", None)
        )
        if first_response is not None and first_response <= 0:
            raise serializers.ValidationError(
                {"first_response_minutes": "Must be greater than zero."}
            )
        if resolution is not None and resolution <= 0:
            raise serializers.ValidationError({"resolution_minutes": "Must be greater than zero."})
        if first_response is not None and resolution is not None and resolution < first_response:
            raise serializers.ValidationError(
                {"resolution_minutes": "Must be at least the first response time."}
            )
        priority = attrs.get("priority", getattr(self.instance, "priority", None))
        is_active = attrs.get("is_active", getattr(self.instance, "is_active", True))
        conflicts = SLAPolicy.objects.filter(priority=priority, is_active=True)
        if self.instance:
            conflicts = conflicts.exclude(pk=self.instance.pk)
        if is_active and conflicts.exists():
            raise serializers.ValidationError(
                {"priority": "An active SLA policy already exists for this priority."}
            )
        return attrs


class TicketListSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id", read_only=True)
    category = CategoryBriefSerializer(read_only=True)
    requester = UserBriefSerializer(read_only=True)
    assignee = UserBriefSerializer(read_only=True)

    class Meta:
        model = Ticket
        fields = (
            "id",
            "title",
            "status",
            "priority",
            "category",
            "requester",
            "assignee",
            "created_at",
            "updated_at",
        )


class SLAObjectiveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("pending", "met", "breached", "not_applicable"))
    due_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)
    breached_at = serializers.DateTimeField(allow_null=True)


class TicketSLASerializer(serializers.Serializer):
    first_response = SLAObjectiveSerializer()
    resolution = SLAObjectiveSerializer()


class TicketDetailSerializer(TicketListSerializer):
    sla = serializers.SerializerMethodField()

    @extend_schema_field(TicketSLASerializer)
    def get_sla(self, obj):
        return {
            "first_response": {
                "status": obj.first_response_sla_status,
                "due_at": obj.first_response_due_at,
                "completed_at": obj.first_responded_at,
                "breached_at": obj.sla_first_response_breached_at,
            },
            "resolution": {
                "status": obj.resolution_sla_status,
                "due_at": obj.resolution_due_at,
                "completed_at": obj.first_resolved_at,
                "breached_at": obj.sla_resolution_breached_at,
            },
        }

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + (
            "description",
            "resolved_at",
            "first_resolved_at",
            "closed_at",
            "first_response_due_at",
            "resolution_due_at",
            "first_responded_at",
            "sla_first_response_breached_at",
            "sla_resolution_breached_at",
            "sla",
        )


class TicketCreateSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=TicketCategory.objects.filter(is_active=True)
    )

    class Meta:
        model = Ticket
        fields = ("title", "description", "priority", "category")


class TicketUpdateSerializer(serializers.ModelSerializer):
    category = serializers.PrimaryKeyRelatedField(
        queryset=TicketCategory.objects.filter(is_active=True), required=False
    )

    class Meta:
        model = Ticket
        fields = ("title", "description", "priority", "category")
        extra_kwargs = {
            "title": {"required": False},
            "description": {"required": False},
            "priority": {"required": False},
        }


class TicketTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Ticket.Status)


class TicketAssignmentSerializer(serializers.Serializer):
    assignee = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role__in=[User.Role.AGENT, User.Role.ADMIN]),
        allow_null=True,
    )


class TicketCommentSerializer(serializers.ModelSerializer):
    author = UserBriefSerializer(read_only=True)

    class Meta:
        model = TicketComment
        fields = ("id", "author", "content", "created_at", "updated_at")
        read_only_fields = ("id", "author", "created_at", "updated_at")


class TicketHistorySerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)

    class Meta:
        model = TicketHistory
        fields = (
            "id",
            "actor",
            "action",
            "field",
            "old_value",
            "new_value",
            "created_at",
        )
        read_only_fields = fields
