from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking, EntryStatus, WaitlistEntry
from .serializers import (
    BookingSerializer,
    WaitlistHistorySerializer,
    WaitlistSerializer,
)
from .services import book_class, cancel_booking, join_waitlist


class ListBookingsAPI(APIView):
    """List confirmed and cancelled bookings belonging to the authenticated user."""

    def get(self, request):
        """Return booking history with class and studio relations fetched together."""
        bookings = Booking.objects.filter(member=request.user).select_related(
            "class_session__studio"
        )
        serializer = BookingSerializer(bookings, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ListWaitlistEntriesAPI(APIView):
    """List waitlist history belonging to the authenticated user."""

    def get(self, request):
        """Return entries in join order with their class and studio details."""
        entries = WaitlistEntry.objects.filter(member=request.user).select_related(
            "class_session__studio"
        )
        serializer = WaitlistHistorySerializer(entries, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BookClassAPI(APIView):
    """Create bookings or replay responses using the Idempotency-Key header."""
    def post(self, request, class_id):
        """Return the service's saved response body and status for this request key."""
        body, response_status = book_class(
            member=request.user,
            class_session_id=class_id,
            idempotency_key=request.headers.get("Idempotency-Key", "")
        )
        return Response(body, status=response_status)


class CancelBookingAPI(APIView):
    """Cancel the authenticated member's booking through the booking service."""
    def post(self, request, booking_id):
        """Cancel an owned booking, settling credits and attempting promotion."""
        cancel_booking(request.user, booking_id)
        return Response(
            {'message': "Booking cancelled succesfully."},
            status=status.HTTP_200_OK
        )


class JoinWaitlistAPI(APIView):
    """Add the authenticated member to an eligible class waitlist."""
    def post(self, request, class_id):
        """Create and return the member's waiting entry."""
        waitlist = join_waitlist(request.user, class_id)
        serializer = WaitlistSerializer(waitlist)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class WithdrawWaitlistEntryAPI(APIView):
    """Withdraw the authenticated member's waiting entry under a row lock."""

    @transaction.atomic
    def post(self, request, class_id):
        """Mark an owned waiting entry withdrawn, or return 404 if none exists."""
        waitlist = WaitlistEntry.objects.select_for_update().filter(
            class_session_id=class_id,
            status=EntryStatus.WAITING,
            member=request.user
        ).first()
        if waitlist:
            waitlist.status = EntryStatus.WITHDRAWN
            waitlist.withdrawn_at = timezone.now()
            waitlist.save(update_fields=["status", "withdrawn_at"])
            serializer = WaitlistSerializer(waitlist)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(
            {"message": "No waiting list entry found."},
            status=status.HTTP_404_NOT_FOUND
        )
