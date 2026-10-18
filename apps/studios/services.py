"""Credit grants and member ledger history."""

from datetime import datetime

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.studios.models import CreditKind, CreditMovement, CreditPack, Studio
from apps.studios.types import CreditGrantData, CreditHistoryEvent


def grant_credit_pack(
    staff: User, studio: Studio, validated_data: CreditGrantData
) -> CreditPack:
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


def _expiry_event(
    pack: CreditPack, amount: int, effective_at: datetime
) -> CreditHistoryEvent:
    """Describe expired credits without storing or deducting them again."""
    return {
        "id": None,
        "kind": CreditKind.EXPIRY,
        "amount": -amount,
        "pack_id": pack.pk,
        "studio": pack.studio,
        "booking_id": None,
        "effective_at": effective_at,
        "recorded_at": None,
    }


def credit_history(member: User) -> list[CreditHistoryEvent]:
    """Combine effective ledger movements with read-only expiry explanations.

    Expiry events are calculated, not persisted. Refunds at or after expiry
    receive a matching expiry event because they retain the pack's expiry.
    """
    now = timezone.now()
    movements = (
        CreditMovement.objects.filter(
            pack__member=member,
            effective_at__lte=now,
        )
        .select_related("pack__studio")
        .order_by("effective_at", "pk")
    )
    events: list[tuple[datetime, int, int, int, CreditHistoryEvent]] = []
    balances_at_expiry: dict[int, int] = {}
    expired_packs: dict[int, CreditPack] = {}

    for movement in movements:
        pack = movement.pack
        # Later refunds must not change the amount that expired originally.
        if movement.effective_at < pack.expires_at:
            balances_at_expiry[pack.pk] = (
                balances_at_expiry.get(pack.pk, 0) + movement.amount
            )
        if pack.expires_at <= now:
            expired_packs[pack.pk] = pack

        event: CreditHistoryEvent = {
            "id": movement.pk,
            "kind": movement.kind,
            "amount": movement.amount,
            "pack_id": pack.pk,
            "studio": pack.studio,
            "booking_id": movement.booking_id,
            "effective_at": movement.effective_at,
            "recorded_at": movement.recorded_at,
        }
        events.append((movement.effective_at, 1, movement.pk, 0, event))

        if (
            movement.kind == CreditKind.REFUND
            and movement.effective_at >= pack.expires_at
        ):
            # Keep a refund and its immediate expiry next to each other in history.
            expiry = _expiry_event(pack, movement.amount, movement.effective_at)
            events.append((movement.effective_at, 1, movement.pk, 1, expiry))

    for pack_id, pack in expired_packs.items():
        amount = balances_at_expiry.get(pack_id, 0)
        if amount > 0:
            expiry = _expiry_event(pack, amount, pack.expires_at)
            # The original expiry comes before movements at the expiry boundary.
            events.append((pack.expires_at, 0, pack.pk, 0, expiry))

    events.sort(key=lambda item: item[:4])
    return [item[4] for item in events]
