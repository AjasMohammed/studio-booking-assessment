from django.db.models import Prefetch, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.studios.models import CreditPack, Studio
from apps.studios.permissions import IsStudioStaff
from apps.studios.serializers import (
    GrantCreditPackSerializer,
    StudioCreditBalanceSerializer,
)
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


class CreditBalanceAPI(APIView):
    def get(self, request):
        member = request.user
        now = timezone.now()
        studio_credit_balance = (
            Studio.objects.filter(
                credit_packs__member=member,
                credit_packs__expires_at__gt=now,
                credit_packs__granted_at__lte=now
            ).annotate(
                total_credits=Sum("credit_packs__credits_remaining", default=0)
            ).prefetch_related(
                Prefetch(
                    "credit_packs",
                    queryset=CreditPack.objects.filter(
                        member=member,
                        expires_at__gt=now,
                        granted_at__lte=now
                    )
                )
            )
        )
        serializer = StudioCreditBalanceSerializer(
            studio_credit_balance, many=True)
        payload = {
            "studios": serializer.data
        }
        return Response(payload, status=status.HTTP_200_OK)
