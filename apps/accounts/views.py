from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.serializers import UserSerializer


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
