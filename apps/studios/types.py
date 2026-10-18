"""Validated credit inputs and ledger response shapes."""

from datetime import date, datetime
from typing import TypedDict

from apps.accounts.models import User
from apps.studios.models import Studio


class CreditGrantData(TypedDict):
    """Credit-pack fields supplied by the validated staff grant request."""

    member: User
    credits_remaining: int
    expires_at: datetime


class CreditHistoryEvent(TypedDict):
    """Response data shared by saved movements and calculated expiry events."""

    id: int | None
    kind: str
    amount: int
    pack_id: int
    studio: Studio
    booking_id: int | None
    effective_at: datetime
    recorded_at: datetime | None


class CreditBalanceQuery(TypedDict, total=False):
    """Optional timestamp accepted by the balance endpoint."""

    at: datetime


class DateRangeData(TypedDict):
    """Inclusive, validated date bounds for browsing classes."""

    start_date: date
    end_date: date
