from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.studios.models import Studio
from apps.studios.permissions import IsStudioStaff
from apps.studios.serializers import GrantCreditPackSerializer
from apps.studios.services import grant_credit_pack


class GrantCreditAPI(APIView):
    permission_classes = (IsStudioStaff,)

    def post(self, request, studio_id: int):
        data: dict = request.data
        studio = get_object_or_404(Studio, pk=studio_id)
        credit_serializer = GrantCreditPackSerializer(data=data)
        credit_serializer.is_valid(raise_exception=True)

        credit_pack = grant_credit_pack(
            request.user, studio, credit_serializer.validated_data)
        payload = {
            "message": "Credit granted successfully!",
            "id": credit_pack.id,
            'status': status.HTTP_201_CREATED
        }
        return Response(payload, status=status.HTTP_201_CREATED)
