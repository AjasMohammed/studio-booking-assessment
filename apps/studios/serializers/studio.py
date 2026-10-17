from datetime import datetime

from rest_framework import serializers

from apps.studios.models import ClassSessions, Studio
from apps.studios.services import is_valid_time

from .credits import CreditBalanceSerializer


class StudioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Studio
        fields = (
            "name",
            "timezone",
            "cancellation_cutoff_hours"
        )


class ClassSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassSessions
        fields = (
            "starts_at",
            "duration_minutes",
            "capacity",
            "credit_cost",
        )

    def validate_starts_at(self, value: datetime) -> datetime:
        is_valid_time(value)
        return value


class ListClassSessionSerializer(serializers.ModelSerializer):
    studio = StudioSerializer()
    no_of_seats_available = serializers.IntegerField(read_only=True)

    class Meta:
        model = ClassSessions
        fields = (
            "studio",
            "starts_at",
            "duration_minutes",
            "capacity",
            "credit_cost",
            "no_of_seats_available"
        )


class DateRangeSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs):
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError(
                {"end_date": "Must be on or after start_date."}
            )
        return attrs


class StudioCreditBalanceSerializer(serializers.ModelSerializer):
    credit_packs = CreditBalanceSerializer(many=True, read_only=True)
    total_credits = serializers.IntegerField(read_only=True)

    class Meta:
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
