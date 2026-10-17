from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.accounts.serializers import UserSerializer
from apps.studios.permissions import IsStudioStaff

UserModel = get_user_model()


class PublicAPIView(APIView):
    """Base view for endpoints that require neither authentication nor permissions."""
    authentication_classes = ()
    permission_classes = ()


class SignUp(PublicAPIView):
    """Accept public account registrations."""
    def post(self, request):
        """Validate registration data and create an account."""
        serializer = UserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "User created successfully!"},
            status=status.HTTP_201_CREATED
        )


class ListMembers(APIView):
    """Allow staff to browse users with the member role."""
    permission_classes = (IsStudioStaff,)

    def get(self, request):
        """Return member accounts without exposing password values."""
        members = UserModel.objects.filter(role=Role.MEMBER)
        serializer = UserSerializer(members, many=True)
        return Response(
            serializer.data, status=status.HTTP_200_OK
        )
