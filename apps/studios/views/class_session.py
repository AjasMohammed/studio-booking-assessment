from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.bookings.models import BookingStatus
from apps.studios.models import ClassSessions, Studio
from apps.studios.permissions import IsStudioStaff
from apps.studios.serializers import (
    ClassSessionSerializer,
    DateRangeSerializer,
    ListClassSessionSerializer,
)


class CreateSession(APIView):
    permission_classes = (IsStudioStaff,)

    def post(self, request, studio_id: int):
        studio = get_object_or_404(Studio, pk=studio_id)
        serializer = ClassSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        class_session: ClassSessions = serializer.save(studio=studio)
        payload = {
            "session_id": class_session.id,
            "studio_id": studio_id,
            "status": status.HTTP_201_CREATED
        }
        return Response(
            payload,
            status=status.HTTP_201_CREATED
        )


class ListClassSessionsAPI(APIView):
    def get(self, request):
        q_params = request.query_params
        now = timezone.now()
        class_sessions = ClassSessions.objects.filter(starts_at__gt=now)
        if q_params:
            params_serializer = DateRangeSerializer(data=q_params)
            params_serializer.is_valid()
            dates = params_serializer.validated_data
            class_sessions = class_sessions.filter(starts_at__date__range=(
                dates['start_date'],
                dates['end_date'],
            ))
        class_sessions = class_sessions.annotate(
            no_of_seats_available=F("capacity") - Count(
                "bookings", filter=Q(bookings__status=BookingStatus.CONFIRMED)
            )
        )
        serializer = ListClassSessionSerializer(class_sessions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
