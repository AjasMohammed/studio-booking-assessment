from datetime import datetime

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.studios.models import CreditKind, CreditMovement, CreditPack


def is_valid_time(value: datetime):
    """Reject a parsed datetime that is not strictly later than the current time."""
    if value <= timezone.now():
        raise serializers.ValidationError(
            "Invalid time provided!"
        )


def grant_credit_pack(staff, studio, validated_data):
    """Create a credit pack and its initial grant movement in one transaction."""
    with transaction.atomic():
        credit_pack = CreditPack.objects.create(
            granted_by=staff,
            studio=studio,
            **validated_data
        )
        CreditMovement.objects.create(
            pack=credit_pack,
            kind=CreditKind.GRANT,
            amount=credit_pack.credits_remaining,
            effective_at=credit_pack.granted_at
        )
    return credit_pack
