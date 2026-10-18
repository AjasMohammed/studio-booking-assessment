from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.accounts.models import Role


class IsStudioStaff(BasePermission):
    """Allow only authenticated users with the application staff role."""
    message = "Only staff can perfrom this action."

    def has_permission(self, request: Request, view: APIView) -> bool:
        """Check authentication before reading the application role."""
        return (
            request.user.is_authenticated
            and request.user.role == Role.STAFF
        )
