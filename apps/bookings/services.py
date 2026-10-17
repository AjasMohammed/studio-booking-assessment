import hashlib
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

from apps.bookings.models import Booking, BookingStatus, IdempotencyRecord
from apps.studios.models import ClassSessions, CreditKind, CreditMovement, CreditPack


class IdempotencyConflict(APIException):
    status_code = 409
    default_detail = "This idempotency key was already used for a different request."
    default_code = "idempotency_conflict"


def _create_booking(member, class_session: ClassSessions, booking_time: datetime):
    candidates = list(
        CreditPack.objects.select_for_update()
        .filter(
            member=member,
            studio_id=class_session.studio_id,
            expires_at__gt=booking_time,
            credits_remaining__gt=0,
        )
        .order_by("expires_at", "pk")
    )
    # The pack query can wait for locks; validate at the actual charging time.
    booking_time = timezone.now()
    if class_session.starts_at <= booking_time:
        raise serializers.ValidationError("Class Already Started!")
    studio_member_credits = [
        pack for pack in candidates if pack.granted_at <= booking_time < pack.expires_at
    ]
    total_available_credits = sum(
        pack.credits_remaining for pack in studio_member_credits
    )
    credits_needed = class_session.credit_cost
    if total_available_credits < credits_needed:
        raise serializers.ValidationError("Insufficient credits!")
    else:
        cutoff_hours = class_session.studio.cancellation_cutoff_hours
        if cutoff_hours == 0:
            deadline = class_session.starts_at
        else:
            local_start = class_session.starts_at.astimezone(
                ZoneInfo(class_session.studio.timezone)
            )
            # Local-clock policy: first occurrence for ambiguous deadlines;
            # nonexistent deadlines shift forward by the DST gap in UTC conversion.
            deadline = (
                (local_start - timedelta(hours=cutoff_hours))
                .replace(fold=0)
                .astimezone(UTC)
            )
        booking, created = Booking.objects.get_or_create(
            member=member,
            class_session=class_session,
            status=BookingStatus.CONFIRMED,
            defaults={
                "credits_charged": credits_needed,
                "cancellation_deadline": deadline,
            },
        )
        if not created:
            raise serializers.ValidationError(
                f"Booking for the session already exists for {member.username}"
            )
        for pack in studio_member_credits:
            if credits_needed == 0:
                break
            credits_to_spend = min(pack.credits_remaining, credits_needed)
            pack.credits_remaining -= credits_to_spend
            credits_needed -= credits_to_spend
            pack.save(update_fields=["credits_remaining"])
            CreditMovement.objects.create(
                pack=pack,
                kind=CreditKind.BOOKING,
                amount=-credits_to_spend,
                effective_at=booking_time,
                booking=booking,
            )
        return booking


@transaction.atomic
def book_class(member, class_session_id, idempotency_key):
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 255:
        raise serializers.ValidationError(
            {"Idempotency-Key": ("Provide a nonblank key of at most 255 characters.")}
        )
    payload = json.dumps(
        {"class_session_id": class_session_id},
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
    # A stable row exists even before a request's idempotency record does.
    # All booking writes use member -> class -> packs as their lock order.
    get_user_model().objects.select_for_update().get(pk=member.pk)
    previous = IdempotencyRecord.objects.filter(
        member=member,
        key=idempotency_key,
    ).first()
    if previous is not None:
        if previous.request_fingerprint != fingerprint:
            raise IdempotencyConflict()

        return previous.response_body, previous.response_status

    session = get_object_or_404(
        ClassSessions.objects.select_for_update(of=("self",)).select_related("studio"),
        pk=class_session_id,
    )
    now = timezone.now()
    if session.starts_at <= now:
        raise serializers.ValidationError("Class Already Started!")
    confirmed_seats_count = session.bookings.filter(
        status=BookingStatus.CONFIRMED
    ).count()
    if session.capacity <= confirmed_seats_count:
        raise serializers.ValidationError("Seats are full!")
    booking = _create_booking(member, session, now)
    body = {
        "id": booking.pk,
        "class_session_id": booking.class_session_id,
        "status": booking.status,
        "credits_charged": booking.credits_charged,
    }
    record = IdempotencyRecord.objects.create(
        member=member,
        key=idempotency_key,
        request_fingerprint=fingerprint,
        booking=booking,
        response_status=201,
        response_body=body,
    )
    return record.response_body, record.response_status
