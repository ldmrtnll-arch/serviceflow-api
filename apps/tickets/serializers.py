from rest_framework import serializers

from apps.accounts.models import User

from .models import Ticket, TicketCategory, TicketComment, TicketHistory


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


class TicketDetailSerializer(TicketListSerializer):
    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + (
            "description",
            "resolved_at",
            "closed_at",
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
