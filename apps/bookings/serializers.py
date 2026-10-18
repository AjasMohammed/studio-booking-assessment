from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.studios.serializers import ClassSessionSerializer, StudioSerializer

from .models import Booking, WaitlistEntry


class BookingClassSessionSerializer(ClassSessionSerializer):
    """Represent class details with the ID and studio configuration."""

    studio = StudioSerializer(read_only=True)

    class Meta(ClassSessionSerializer.Meta):
        """Extend scheduling fields with the identifiers needed by clients."""

        fields = ("id", "studio", *ClassSessionSerializer.Meta.fields)
        read_only_fields = fields


class BookingSerializer(serializers.ModelSerializer[Booking]):
    """Represent booking history with class details and captured booking terms."""

    class_session = BookingClassSessionSerializer(read_only=True)

    class Meta:
        """Expose booking details without accepting writes through this serializer."""

        model = Booking
        fields = (
            "id",
            "status",
            "class_session",
            "credits_charged",
            "cancellation_deadline",
            "booked_at",
            "cancelled_at",
        )
        read_only_fields = fields


class WaitlistHistorySerializer(serializers.ModelSerializer[WaitlistEntry]):
    """Represent a member's waitlist history, including its resulting booking ID."""

    class_session = BookingClassSessionSerializer(read_only=True)
    booking_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        """Expose entry status, lifecycle timestamps, and related class details."""

        model = WaitlistEntry
        fields = (
            "id",
            "status",
            "class_session",
            "joined_at",
            "promoted_at",
            "withdrawn_at",
            "booking_id",
        )
        read_only_fields = fields


class WaitlistSerializer(serializers.ModelSerializer[WaitlistEntry]):
    """Represent a waitlist entry with nested member and class details."""
    class_session = ClassSessionSerializer()
    member = UserSerializer()

    class Meta:
        """Declare serialized fields and their model mapping."""
        model = WaitlistEntry
        fields = (
            "id",
            "member",
            "status",
            "class_session"
        )
