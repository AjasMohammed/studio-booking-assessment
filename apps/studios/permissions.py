from rest_framework.permissions import BasePermission

from apps.accounts.models import Role


class IsStudioStaff(BasePermission):
    """Allow only authenticated users with the application staff role."""
    message = "Only staff can perfrom this action."

    def has_permission(self, request, view):
        """Check authentication before reading the application role."""
        return (
            request.user.is_authenticated and request.user.role == Role.STAFF
        )
