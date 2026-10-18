"""Read-only queries for member credit balances."""

from datetime import datetime

from django.db.models import Prefetch, Q, QuerySet, Sum
from django.utils import timezone

from apps.accounts.models import User
from apps.studios.models import CreditPack, Studio


def credit_balances(member: User, at: datetime | None = None) -> QuerySet[Studio]:
    """Group eligible packs by studio, reconstructing past amounts when requested."""
    balance_time = at if at is not None else timezone.now()
    packs = CreditPack.objects.filter(
        member=member,
        expires_at__gt=balance_time,
        granted_at__lte=balance_time,
    )
    total = Sum("credit_packs__credits_remaining", default=0)
    if at is not None:
        # Today's pack balance cannot reconstruct charges or refunds at a past time.
        packs = packs.annotate(
            balance_at=Sum(
                "movements__amount",
                filter=Q(movements__effective_at__lte=at),
                default=0,
            )
        )
        total = Sum(
            "credit_packs__movements__amount",
            filter=Q(credit_packs__movements__effective_at__lte=at),
            default=0,
        )
    # Keep aggregate and prefetch filters aligned with the displayed packs.
    studio_credit_balance = (
        Studio.objects.filter(
            credit_packs__member=member,
            credit_packs__expires_at__gt=balance_time,
            credit_packs__granted_at__lte=balance_time,
        ).annotate(
            total_credits=total,
        ).prefetch_related(
            Prefetch("credit_packs", queryset=packs)
        )
    )
    return studio_credit_balance
