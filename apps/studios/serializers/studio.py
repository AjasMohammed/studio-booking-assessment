from datetime import datetime

from rest_framework import serializers

from apps.studios.models import ClassSessions, Studio
from apps.studios.types import DateRangeData
from apps.studios.validators import is_valid_time


class StudioSerializer(serializers.ModelSerializer[Studio]):
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


class ClassSessionSerializer(serializers.ModelSerializer[ClassSessions]):
    """Validate class scheduling fields, including a future start time."""
    class Meta:
        """Declare serialized fields and their model mapping."""
        model = ClassSessions
        fields: tuple[str, ...] = (
            "starts_at",
            "duration_minutes",
            "capacity",
            "credit_cost",
        )

    def validate_starts_at(self, value: datetime) -> datetime:
        """Require the parsed, timezone-aware class start to be in the future."""
        is_valid_time(value)
        return value


class ListClassSessionSerializer(serializers.ModelSerializer[ClassSessions]):
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


class DateRangeSerializer(serializers.Serializer[DateRangeData]):
    """Validate inclusive date-range bounds for class browsing."""
    start_date = serializers.DateField()
    end_date = serializers.DateField()

    def validate(self, attrs: DateRangeData) -> DateRangeData:
        """Reject a range whose end precedes its start."""
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError(
                {"end_date": "Must be on or after start_date."}
            )
        return attrs
