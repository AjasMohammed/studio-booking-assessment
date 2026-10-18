"""Typed inputs and results shared by the test helpers."""

from datetime import datetime
from typing import NotRequired, TypedDict

from apps.accounts.models import User
from apps.bookings.types import BookingResponse
from apps.studios.models import Studio


class SessionOverrides(TypedDict, total=False):
    studio: Studio
    starts_at: datetime
    duration_minutes: int
    capacity: int
    credit_cost: int


class PackOverrides(TypedDict, total=False):
    member: User
    studio: Studio
    granted_by: User
    credits_remaining: int
    granted_at: datetime
    expires_at: datetime


class RaceResult(TypedDict):
    status: int
    body: NotRequired[BookingResponse]
    error: NotRequired[str]
