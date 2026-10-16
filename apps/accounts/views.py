from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role
from apps.accounts.serializers import UserSerializer
from apps.studios.permissions import IsStudioStaff

UserModel = get_user_model()


class PublicAPIView(APIView):
    authentication_classes = ()
    permission_classes = ()


class SignUp(PublicAPIView):
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"message": "User created successfully!"},
            status=status.HTTP_201_CREATED
        )


class ListMembers(APIView):
    permission_classes = (IsStudioStaff,)
    def get(self, request):
        members = UserModel.objects.filter(role=Role.MEMBER)
        serializer = UserSerializer(members, many=True)
        return Response(
            serializer.data, status=status.HTTP_200_OK
        )
