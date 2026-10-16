from datetime import datetime

from django.utils import timezone
from rest_framework import serializers

from apps.studios.models import ClassSessions, Studio


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
        if value <= timezone.now():
            raise serializers.ValidationError(
                "Invalid time provided!"
            )
        return value
