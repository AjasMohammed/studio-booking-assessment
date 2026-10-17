from datetime import datetime

from django.utils import timezone
from rest_framework import serializers

from apps.studios.models import CreditPack
from apps.studios.services import is_valid_time


class CreditBalanceQuerySerializer(serializers.Serializer):
    """Accept an optional historical balance timestamp; future snapshots are invalid."""

    at = serializers.DateTimeField(required=False)

    def validate_at(self, value):
        """Require the snapshot to be at or before the current time."""
        if value > timezone.now():
            raise serializers.ValidationError("Must not be in the future.")
        return value


class GrantCreditPackSerializer(serializers.ModelSerializer):
    """Validate positive credit grants within the database integer range."""
    credits_remaining = serializers.IntegerField(min_value=1, max_value=2_147_483_647)

    class Meta:
        """Declare serialized fields and their model mapping."""
        model = CreditPack
        fields = (
            "member",
            "credits_remaining",
            "expires_at",
        )

    def validate_expires_at(self, value: datetime) -> datetime:
        """Require the parsed expiry timestamp to be in the future."""
        is_valid_time(value)
        return value


class CreditBalanceSerializer(serializers.ModelSerializer):
    """Represent the remaining balance, expiry, and grantor of a pack."""
    class Meta:
        """Declare serialized fields and their model mapping."""
        model = CreditPack
        fields = ("credits_remaining", "expires_at", "granted_by")


class HistoricalCreditBalanceSerializer(CreditBalanceSerializer):
    """Use the movement-derived snapshot in place of today's stored pack balance."""

    credits_remaining = serializers.IntegerField(source="balance_at", read_only=True)
