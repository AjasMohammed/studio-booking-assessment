"""Validation shared by studio serializers."""

from datetime import datetime

from django.utils import timezone
from rest_framework import serializers


def is_valid_time(value: datetime) -> None:
    """Reject a parsed datetime that is not strictly later than the current time."""
    if value <= timezone.now():
        raise serializers.ValidationError(
            "Invalid time provided!"
        )
