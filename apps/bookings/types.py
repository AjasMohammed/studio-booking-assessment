"""Response shapes stored for booking retries."""

from typing import TypedDict


class BookingResponse(TypedDict):
    """Successful booking response persisted for idempotent retries."""

    id: int
    class_session_id: int
    status: str
    credits_charged: int
