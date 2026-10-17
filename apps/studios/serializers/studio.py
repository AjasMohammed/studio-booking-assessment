from datetime import datetime

from rest_framework import serializers

from apps.studios.models import ClassSessions, CreditMovement, Studio
from apps.studios.services import is_valid_time

from .credits import CreditBalanceSerializer, HistoricalCreditBalanceSerializer


class StudioSerializer(serializers.ModelSerializer):
    """Validate and represent studio configuration."""
    class Meta:
        """Declare serialized fields and their model mapping."""
        model = Studio
        fields = (
            "id",
            "name",
            "timezone",
            "cancellation_cutoff_hours"
        )
        read_only_fields = ("id",)


class CreditMovementSerializer(serializers.ModelSerializer):
    """Represent a signed credit event with its pack, studio, and booking references."""

    pack_id = serializers.IntegerField(read_only=True)
    booking_id = serializers.IntegerField(read_only=True, allow_null=True)
    studio = StudioSerializer(source="pack.studio", read_only=True)

    class Meta:
        """Expose accounting causes and timestamps without accepting ledger writes."""

        model = CreditMovement
        fields = (
            "id",
            "kind",
            "amount",
            "pack_id",
            "studio",
            "booking_id",
            "effective_at",
            "recorded_at",
        )
        read_only_fields = fields


class ClassSessionSerializer(serializers.ModelSerializer):
    """Validate class scheduling fields, including a future start time."""
    class Meta:
        """Declare serialized fields and their model mapping."""
        model = ClassSessions
        fields = (
            "starts_at",
            "duration_minutes",
            "capacity",
            "credit_cost",
        )

    def validate_starts_at(self, value: datetime) -> datetime:
        """Require the parsed, timezone-aware class start to be in the future."""
        is_valid_time(value)
        return value


class ListClassSessionSerializer(serializers.ModelSerializer):
    """Represent class details with the annotated remaining seat count."""
    studio = StudioSerializer()
    no_of_seats_available = serializers.IntegerField(read_only=True)

    class Meta:
        """Declare serialized fields and their model mapping."""
        model = ClassSessions
        fields = (
            "id",
            "studio",
            "starts_at",
            "duration_minutes",
            "capacity",
            "credit_cost",
            "no_of_seats_available"
        )
        read_only_fields = ("id",)


class DateRangeSerializer(serializers.Serializer):
    """Validate inclusive date-range bounds for class browsing."""
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        """Reject a range whose end precedes its start."""
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError(
                {"end_date": "Must be on or after start_date."}
            )
        return attrs


class StudioCreditBalanceSerializer(serializers.ModelSerializer):
    """Represent a studio balance and its prefetched member credit packs."""
    credit_packs = CreditBalanceSerializer(many=True, read_only=True)
    total_credits = serializers.IntegerField(read_only=True)

    class Meta:
        """Declare serialized fields and their model mapping."""
        model = Studio
        fields = (
            "id",
            "name",
            "timezone",
            "cancellation_cutoff_hours",
            "total_credits",
            "credit_packs"
        )
        read_only_fields = (
            "id",
            "name",
            "timezone",
            "cancellation_cutoff_hours",
        )


class HistoricalStudioCreditBalanceSerializer(StudioCreditBalanceSerializer):
    """Represent studio totals and pack balances reconstructed at a past instant."""

    credit_packs = HistoricalCreditBalanceSerializer(many=True, read_only=True)
