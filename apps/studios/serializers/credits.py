from datetime import datetime

from rest_framework import serializers

from apps.studios.models import CreditPack
from apps.studios.services import is_valid_time


class GrantCreditPackSerializer(serializers.ModelSerializer):
    credits_granted = serializers.IntegerField(min_value=1)

    class Meta:
        model = CreditPack
        fields = (
            "member",
            "credits_granted",
            "expires_at",
        )

    def validate_expires_at(self, value: datetime) -> datetime:
        is_valid_time(value)
        return value

    # def validate_credits_granted(self, value: int) -> int:
    #     if value <= 0:
    #         raise serializers.ValidationError(
    #             "The credit amount should be greater than 0."
    #         )
    #     return value
