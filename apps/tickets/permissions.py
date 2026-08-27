from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import User


class IsAdminOrReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or request.user.role == User.Role.ADMIN


class SLAPolicyPermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return request.user.role in {User.Role.AGENT, User.Role.ADMIN}
        return request.user.role == User.Role.ADMIN


class IsOperator(BasePermission):
    def has_permission(self, request, view):
        return request.user.role in {User.Role.AGENT, User.Role.ADMIN}
