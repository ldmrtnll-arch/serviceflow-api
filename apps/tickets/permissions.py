from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import User


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or request.user.role == User.Role.ADMIN
