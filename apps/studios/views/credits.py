from django.db.models import Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.studios.models import CreditMovement, CreditPack, Studio
from apps.studios.permissions import IsStudioStaff
from apps.studios.serializers import (
    CreditBalanceQuerySerializer,
    CreditMovementSerializer,
    GrantCreditPackSerializer,
    HistoricalStudioCreditBalanceSerializer,
    StudioCreditBalanceSerializer,
)
from apps.studios.services import grant_credit_pack


class CreditMovementAPI(APIView):
    """List credit movements belonging to the authenticated user's packs."""

    def get(self, request):
        """Return stored events in accounting order, including expired pack history."""
        movements = CreditMovement.objects.filter(
            pack__member=request.user
        ).select_related("pack__studio")
        serializer = CreditMovementSerializer(movements, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class GrantCreditAPI(APIView):
    """Allow staff to grant a credit pack in the studio identified by the URL."""
    permission_classes = (IsStudioStaff,)

    def post(self, request, studio_id: int):
        """Validate a grant and create its pack and accounting movement together."""
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
    """Report current or historical spendable credits grouped by studio."""
    def get(self, request):
        """Use movements for an explicit snapshot and stored balances otherwise."""
        # Validate an explicit ?at= as blank input instead of an omitted HTML field.
        params = CreditBalanceQuerySerializer(data=request.query_params.dict())
        params.is_valid(raise_exception=True)
        at = params.validated_data.get("at")
        member = request.user
        balance_time = at if at is not None else timezone.now()
        packs = CreditPack.objects.filter(
            member=member,
            expires_at__gt=balance_time,
            granted_at__lte=balance_time,
        )
        serializer_class = StudioCreditBalanceSerializer
        total = Sum("credit_packs__credits_remaining", default=0)
        if at is not None:
            # Today's pack balance cannot reconstruct charges or refunds at a past time.
            packs = packs.annotate(
                balance_at=Sum(
                    "movements__amount",
                    filter=Q(movements__effective_at__lte=at),
                    default=0,
                )
            )
            total = Sum(
                "credit_packs__movements__amount",
                filter=Q(credit_packs__movements__effective_at__lte=at),
                default=0,
            )
            serializer_class = HistoricalStudioCreditBalanceSerializer
        # Keep aggregate and prefetch filters aligned with the displayed packs.
        studio_credit_balance = (
            Studio.objects.filter(
                credit_packs__member=member,
                credit_packs__expires_at__gt=balance_time,
                credit_packs__granted_at__lte=balance_time,
            ).annotate(
                total_credits=total,
            ).prefetch_related(
                Prefetch("credit_packs", queryset=packs)
            )
        )
        serializer = serializer_class(
            studio_credit_balance, many=True)
        payload = {
            "studios": serializer.data
        }
        return Response(payload, status=status.HTTP_200_OK)
