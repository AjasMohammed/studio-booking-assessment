from datetime import datetime

from rest_framework import serializers

from apps.studios.models import ClassSessions, Studio
from apps.studios.services import is_valid_time


class StudioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Studio
        fields = "__all__"


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
