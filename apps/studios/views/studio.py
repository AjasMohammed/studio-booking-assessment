from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.studios.models import Studio
from apps.studios.permissions import IsStudioStaff
from apps.studios.serializers import StudioSerializer


class CreateStudio(APIView):
    """Allow staff to create a studio and its cancellation policy."""
    permission_classes = (IsStudioStaff,)

    def post(self, request: Request) -> Response:
        """Validate studio settings and return the created studio ID."""
        data = request.data
        serizlizer = StudioSerializer(data=data)
        serizlizer.is_valid(raise_exception=True)
        studio: Studio = serizlizer.save()
        payload = {
            "studio_id": studio.id,
            "status": status.HTTP_201_CREATED
        }
        return Response(
            payload, status=status.HTTP_201_CREATED
        )


class ListStudiosAPI(APIView):
    """Allow staff to browse studio configuration."""
    permission_classes = (IsStudioStaff,)

    def get(self, request: Request) -> Response:
        """Return all studio configurations to staff."""
        studios = Studio.objects.all()
        serializer = StudioSerializer(studios, many=True)
        return Response(
            serializer.data, status=status.HTTP_200_OK
        )
