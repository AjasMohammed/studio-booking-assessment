from rest_framework.permissions import BasePermission

from apps.accounts.models import Role


class IsStudioStaff(BasePermission):
    message = "Only staff can perfrom this action."

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and request.user.role == Role.STAFF
        )
