"""Serialization of saved and calculated credit-history events."""

from rest_framework import serializers

from apps.studios.types import CreditHistoryEvent

from .studio import StudioSerializer


class CreditMovementSerializer(serializers.Serializer[CreditHistoryEvent]):
    """Represent stored movements and calculated expiry events using one shape."""

    id = serializers.IntegerField(read_only=True, allow_null=True)
    kind = serializers.CharField(read_only=True)
    amount = serializers.IntegerField(read_only=True)
    pack_id = serializers.IntegerField(read_only=True)
    booking_id = serializers.IntegerField(read_only=True, allow_null=True)
    studio = StudioSerializer(read_only=True)
    effective_at = serializers.DateTimeField(read_only=True)
    recorded_at = serializers.DateTimeField(read_only=True, allow_null=True)
