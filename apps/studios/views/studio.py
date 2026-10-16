from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.studios.models import Studio
from apps.studios.permissions import IsStudioStaff
from apps.studios.serializers import StudioSerializer


class CreateStudio(APIView):
    permission_classes = (IsStudioStaff)

    def post(self, request):
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
    permission_classes = (IsStudioStaff)

    def get(self, request):
        studios = Studio.objects.all()
        serializer = StudioSerializer(studios, many=True)
        return Response(
            serializer.data, status=status.HTTP_200_OK
        )
