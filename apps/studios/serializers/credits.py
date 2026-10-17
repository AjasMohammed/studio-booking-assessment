from datetime import datetime

from rest_framework import serializers

from apps.studios.models import CreditPack
from apps.studios.services import is_valid_time


class GrantCreditPackSerializer(serializers.ModelSerializer):
    credits_remaining = serializers.IntegerField(min_value=1, max_value=2_147_483_647)

    class Meta:
        model = CreditPack
        fields = (
            "member",
            "credits_remaining",
            "expires_at",
        )

    def validate_expires_at(self, value: datetime) -> datetime:
        is_valid_time(value)
        return value


class CreditBalanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditPack
        fields = ("credits_remaining", "expires_at", "granted_by")
