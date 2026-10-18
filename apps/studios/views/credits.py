from typing import cast

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.studios.models import Studio
from apps.studios.permissions import IsStudioStaff
from apps.studios.selectors import credit_balances
from apps.studios.serializers import (
    CreditBalanceQuerySerializer,
    CreditMovementSerializer,
    GrantCreditPackSerializer,
    HistoricalStudioCreditBalanceSerializer,
    StudioCreditBalanceSerializer,
)
from apps.studios.services import credit_history, grant_credit_pack
from apps.studios.types import CreditBalanceQuery, CreditGrantData


class CreditMovementAPI(APIView):
    """List the member's credit movements and calculated expiry events."""

    def get(self, request: Request) -> Response:
        """Explain balance changes without writing to the credit ledger."""
        events = credit_history(cast(User, request.user))
        # many=True accepts lists; the plain Serializer stubs only model one instance.
        serializer = CreditMovementSerializer(events, many=True)  # type: ignore[arg-type]
        return Response(serializer.data, status=status.HTTP_200_OK)


class GrantCreditAPI(APIView):
    """Allow staff to grant a credit pack in the studio identified by the URL."""
    permission_classes = (IsStudioStaff,)

    def post(self, request: Request, studio_id: int) -> Response:
        """Validate a grant and create its pack and accounting movement together."""
        data = request.data
        studio = get_object_or_404(Studio, pk=studio_id)
        credit_serializer = GrantCreditPackSerializer(data=data)
        credit_serializer.is_valid(raise_exception=True)

        credit_pack = grant_credit_pack(
            cast(User, request.user),
            studio,
            cast(CreditGrantData, credit_serializer.validated_data),
        )
        payload = {
            "message": "Credit granted successfully!",
            "id": credit_pack.id,
            'status': status.HTTP_201_CREATED
        }
        return Response(payload, status=status.HTTP_201_CREATED)


class CreditBalanceAPI(APIView):
    """Report current or historical spendable credits grouped by studio."""
    def get(self, request: Request) -> Response:
        """Use movements for an explicit snapshot and stored balances otherwise."""
        # Validate an explicit ?at= as blank input instead of an omitted HTML field.
        params = CreditBalanceQuerySerializer(data=request.query_params.dict())
        params.is_valid(raise_exception=True)
        at = cast(CreditBalanceQuery, params.validated_data).get("at")
        member = cast(User, request.user)
        studio_credit_balance = credit_balances(member, at)
        serializer_class = (
            HistoricalStudioCreditBalanceSerializer
            if at is not None else StudioCreditBalanceSerializer
        )
        serializer = serializer_class(
            studio_credit_balance, many=True)
        payload = {
            "studios": serializer.data
        }
        return Response(payload, status=status.HTTP_200_OK)
