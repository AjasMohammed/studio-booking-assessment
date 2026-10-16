from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.studios.models import ClassSessions, Studio
from apps.studios.serializers import ClassSessionSerializer


class CreateSession(APIView):
    def post(self, request, studio_id: int):
        studio = get_object_or_404(Studio, pk=studio_id)
        serializer = ClassSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        class_session: ClassSessions = serializer.save(studio=studio)
        payload = {
            "session_id": class_session.id,
            "status": status.HTTP_201_CREATED
        }
        return Response(
            payload,
            status=status.HTTP_201_CREATED
        )
