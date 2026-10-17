from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class CreditPack(models.Model):
    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="credit_packs",
        limit_choices_to={"role": "member"},
    )
    studio = models.ForeignKey(
        "studios.Studio", on_delete=models.PROTECT, related_name="credit_packs"
    )
    credits_remaining = models.PositiveIntegerField(null=False)
    granted_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(null=False)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="granted_credit_packs",
        limit_choices_to={"role": "staff"},
    )

    class Meta:
        ordering = ["expires_at", "pk"]
        indexes = [models.Index(fields=["member", "studio", "expires_at"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("granted_at")),
                name="pack_expiry_after_grant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.member.username} - {self.studio.name}"


class CreditKind(models.TextChoices):
    GRANT = "grant", "Grant"
    BOOKING = "booking", "Booking charge"
    REFUND = "refund", "Cancellation refund"
    EXPIRY = "expiry", "Expiry"


class CreditMovement(models.Model):
    pack = models.ForeignKey(
        CreditPack, on_delete=models.PROTECT, related_name="movements"
    )
    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.PROTECT,
        related_name="credit_movements",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=10, choices=CreditKind.choices)
    amount = models.IntegerField()
    effective_at = models.DateTimeField(default=timezone.now)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["effective_at", "pk"]
        indexes = [models.Index(fields=["pack", "effective_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind__in=["grant", "refund"], amount__gt=0)
                    | Q(kind__in=["booking", "expiry"], amount__lt=0)
                ),
                name="movement_kind_matches_sign",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind__in=["booking", "refund"], booking__isnull=False)
                    | Q(kind__in=["grant", "expiry"], booking__isnull=True)
                ),
                name="movement_booking_matches_kind",
            ),
            models.UniqueConstraint(
                fields=["pack"], condition=Q(kind="grant"), name="one_grant_per_pack"
            ),
            models.UniqueConstraint(
                fields=["pack", "booking", "kind"],
                condition=Q(kind__in=["booking", "refund"]),
                name="one_charge_or_refund_per_pack_booking",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.kind}: {self.amount:+d} credits (pack {self.pack_id})"

    def clean(self) -> None:
        super().clean()
        if self.pack_id and self.booking_id:
            if self.pack.member_id != self.booking.member_id:
                raise ValidationError(
                    "Pack and booking must belong to the same member."
                )
            if self.pack.studio_id != self.booking.class_session.studio_id:
                raise ValidationError(
                    "Pack and booking must belong to the same studio."
                )
        if (
            self.pack_id
            and self.kind == CreditKind.GRANT
            # Existing grants describe the original amount, not today's balance.
            and self._state.adding
            and self.amount != self.pack.credits_remaining
        ):
            raise ValidationError("Grant movement must match the pack's grant amount.")
