from typing import cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class BookingStatus(models.TextChoices):
    """Persisted states of a class booking."""
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"


class Booking(models.Model):

    """A member reservation with a snapshot of its charged cost and cutoff."""
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    class_session = models.ForeignKey(
        "studios.ClassSessions", on_delete=models.PROTECT, related_name="bookings"
    )
    status = models.CharField(
        max_length=10, choices=BookingStatus.choices, default=BookingStatus.CONFIRMED
    )
    # Preserve booking terms when class prices or studio policies change.
    credits_charged = models.PositiveIntegerField(default=0)
    cancellation_deadline = models.DateTimeField()
    booked_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Configure database integrity rules and query defaults."""
        ordering = ["-booked_at", "-pk"]
        indexes = [models.Index(fields=["class_session", "status"])]
        constraints = [
            # Historical attempts remain; only one active reservation is allowed.
            models.UniqueConstraint(
                fields=["member", "class_session"],
                condition=Q(status="confirmed"),
                name="one_confirmed_booking_per_member_class",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="confirmed", cancelled_at__isnull=True)
                    | Q(status="cancelled", cancelled_at__isnull=False)
                ),
                name="booking_cancellation_matches_status",
            ),
        ]

    def __str__(self) -> str:
        """Return a readable label for admin and diagnostic output."""
        return f"Member {self.member_id}, class {self.class_session_id}: {self.status}"


class EntryStatus(models.TextChoices):
    """Persisted states of a waitlist entry."""
    WAITING = "waiting", "Waiting"
    PROMOTED = "promoted", "Promoted"
    WITHDRAWN = "withdrawn", "Withdrawn"


class WaitlistEntry(models.Model):
    """Track a waitlist attempt and its resulting booking when promoted."""
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="waitlist_entries",
        limit_choices_to={"role": "member"},
    )
    class_session = models.ForeignKey(
        "studios.ClassSessions",
        on_delete=models.PROTECT,
        related_name="waitlist_entries",
    )
    status = models.CharField(
        max_length=10, choices=EntryStatus.choices, default=EntryStatus.WAITING
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    promoted_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    booking = models.OneToOneField(
        Booking,
        on_delete=models.PROTECT,
        related_name="waitlist_entry",
        null=True,
        blank=True,
    )

    class Meta:
        """Configure database integrity rules and query defaults."""
        ordering = ["joined_at", "pk"]
        indexes = [models.Index(
            fields=["class_session", "status", "joined_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["member", "class_session"],
                condition=Q(status="waiting"),
                name="one_waiting_entry_per_member_class",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="waiting",
                        booking__isnull=True,
                        promoted_at__isnull=True,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        status="promoted",
                        booking__isnull=False,
                        promoted_at__isnull=False,
                        withdrawn_at__isnull=True,
                    )
                    | Q(
                        status="withdrawn",
                        booking__isnull=True,
                        promoted_at__isnull=True,
                        withdrawn_at__isnull=False,
                    )
                ),
                name="waitlist_state_consistent",
            ),
        ]

    def __str__(self) -> str:
        """Return a readable label for admin and diagnostic output."""
        return f"Member {self.member_id}, class {self.class_session_id}: {self.status}"

    def clean(self) -> None:
        """Require any promoted booking to match this entry's member and class."""
        super().clean()
        if self.booking_id:
            booking = cast(Booking, self.booking)
            if (
                booking.member_id != self.member_id
                or booking.class_session_id != self.class_session_id
            ):
                raise ValidationError(
                    "Promoted booking must match the member and class.")


class IdempotencyRecord(models.Model):
    """Store a member-scoped request fingerprint and its successful booking response."""
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="booking_idempotency_records",
    )
    key = models.CharField(max_length=255)
    request_fingerprint = models.CharField(max_length=64)
    booking = models.OneToOneField(
        Booking, on_delete=models.PROTECT, related_name="idempotency_record"
    )
    response_status = models.PositiveSmallIntegerField(default=201)
    response_body = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Configure database integrity rules and query defaults."""
        constraints = [
            models.UniqueConstraint(
                fields=["member", "key"], name="unique_member_booking_key"
            ),
            models.CheckConstraint(
                condition=~Q(key=""), name="idempotency_key_not_empty"
            ),
            models.CheckConstraint(
                condition=Q(response_status__gte=200, response_status__lt=300),
                name="idempotency_success_status",
            ),
        ]

    def __str__(self) -> str:
        """Return a readable label for admin and diagnostic output."""
        return f"Booking request for member {self.member_id}: {self.key}"

    def clean(self) -> None:
        """Require the saved booking to belong to the key's member."""
        super().clean()
        if self.booking_id and self.booking.member_id != self.member_id:
            raise ValidationError(
                "Idempotency record must belong to the booking member."
            )
