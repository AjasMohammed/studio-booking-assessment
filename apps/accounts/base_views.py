"""Shared authentication policy for public account endpoints."""

from rest_framework.views import APIView


class PublicAPIView(APIView):
    """Base view for endpoints that require neither authentication nor permissions."""
    authentication_classes = ()
    permission_classes = ()
