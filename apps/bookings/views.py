from typing import cast

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User

from .models import Booking, WaitlistEntry
from .serializers import (
    BookingSerializer,
    WaitlistHistorySerializer,
    WaitlistSerializer,
)
from .services import book_class, cancel_booking, join_waitlist, withdraw_waitlist_entry


class ListBookingsAPI(APIView):
    """List confirmed and cancelled bookings belonging to the authenticated user."""

    def get(self, request: Request) -> Response:
        """Return booking history with class and studio relations fetched together."""
        bookings = Booking.objects.filter(
            member=cast(User, request.user)
        ).select_related("class_session__studio")
        serializer = BookingSerializer(bookings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ListWaitlistEntriesAPI(APIView):
    """List waitlist history belonging to the authenticated user."""

    def get(self, request: Request) -> Response:
        """Return entries in join order with their class and studio details."""
        entries = WaitlistEntry.objects.filter(
            member=cast(User, request.user)
        ).select_related("class_session__studio")
        serializer = WaitlistHistorySerializer(entries, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BookClassAPI(APIView):
    """Create bookings or replay responses using the Idempotency-Key header."""
    def post(self, request: Request, class_id: int) -> Response:
        """Return the service's saved response body and status for this request key."""
        body, response_status = book_class(
            member=cast(User, request.user),
            class_session_id=class_id,
            idempotency_key=request.headers.get("Idempotency-Key", "")
        )
        return Response(body, status=response_status)


class CancelBookingAPI(APIView):
    """Cancel the authenticated member's booking through the booking service."""
    def post(self, request: Request, booking_id: int) -> Response:
        """Cancel an owned booking, settling credits and attempting promotion."""
        cancel_booking(cast(User, request.user), booking_id)
        return Response(
            {'message': "Booking cancelled succesfully."},
            status=status.HTTP_200_OK
        )


class JoinWaitlistAPI(APIView):
    """Add the authenticated member to an eligible class waitlist."""
    def post(self, request: Request, class_id: int) -> Response:
        """Create and return the member's waiting entry."""
        waitlist = join_waitlist(cast(User, request.user), class_id)
        serializer = WaitlistSerializer(waitlist)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WithdrawWaitlistEntryAPI(APIView):
    """Withdraw the authenticated member's waiting entry under a row lock."""

    def post(self, request: Request, class_id: int) -> Response:
        """Mark an owned waiting entry withdrawn, or return 404 if none exists."""
        waitlist = withdraw_waitlist_entry(cast(User, request.user), class_id)
        if waitlist is not None:
            serializer = WaitlistSerializer(waitlist)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(
            {"message": "No waiting list entry found."},
            status=status.HTTP_404_NOT_FOUND,
        )
