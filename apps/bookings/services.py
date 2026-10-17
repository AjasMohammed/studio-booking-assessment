import hashlib
import json
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.models import (
    Booking,
    BookingStatus,
    EntryStatus,
    IdempotencyRecord,
    WaitlistEntry,
)
from apps.studios.models import ClassSessions, CreditKind, CreditMovement, CreditPack

from .exceptions import (
    ClassAlreadyStarted,
    IdempotencyConflict,
    InsufficientCredits,
    NoSeatsAvailable,
)


def check_class_availability(session: ClassSessions):
    now = timezone.now()
    if session.starts_at <= now:
        raise ClassAlreadyStarted()
    confirmed_seats_count = session.bookings.filter(
        status=BookingStatus.CONFIRMED
    ).count()
    if session.capacity <= confirmed_seats_count:
        raise NoSeatsAvailable()


def _create_booking(member_id, class_session: ClassSessions, ):
    candidates = list(
        CreditPack.objects.select_for_update()
        .filter(
            member_id=member_id,
            studio_id=class_session.studio_id,
            expires_at__gt=timezone.now(),
            credits_remaining__gt=0,
        )
        .order_by("expires_at", "pk")
    )
    check_class_availability(class_session)
    booking_time = timezone.now()
    studio_member_credits = [
        pack for pack in candidates if pack.granted_at <= booking_time < pack.expires_at
    ]
    total_available_credits = sum(
        pack.credits_remaining for pack in studio_member_credits
    )
    credits_needed = class_session.credit_cost
    if total_available_credits < credits_needed:
        raise InsufficientCredits()
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
            member_id=member_id,
            class_session=class_session,
            status=BookingStatus.CONFIRMED,
            defaults={
                "credits_charged": credits_needed,
                "cancellation_deadline": deadline,
            },
        )
        if not created:
            raise serializers.ValidationError(
                "Booking for the session already exists for the user"
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
    get_user_model().objects.select_for_update(no_key=True).get(pk=member.pk)
    previous = IdempotencyRecord.objects.filter(
        member=member,
        key=idempotency_key,
    ).first()
    if previous is not None:
        if previous.request_fingerprint != fingerprint:
            raise IdempotencyConflict()

        return previous.response_body, previous.response_status

    session = get_object_or_404(
        ClassSessions.objects.select_for_update(
            of=("self",)).select_related("studio"),
        pk=class_session_id,
    )
    # check_class_availability(session)
    booking = _create_booking(member.id, session)
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


@transaction.atomic
def cancel_booking(member, booking_id):
    get_user_model().objects.select_for_update(no_key=True).get(pk=member.pk)
    booking = get_object_or_404(
        Booking.objects.select_for_update(of=("self",))
        .filter(member=member),
        pk=booking_id
    )
    # Lock this class so other requests wait while we cancel and fill the freed seat.
    get_object_or_404(
        ClassSessions.objects.select_for_update(), pk=booking.class_session_id)
    if booking.status == BookingStatus.CANCELLED:
        raise serializers.ValidationError("Booking already cancelled!")
    now = timezone.now()
    can_refund = booking.cancellation_deadline >= now
    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = now
    booking.save(update_fields=["status", "cancelled_at"])
    if can_refund:
        charges: list[CreditMovement] = list(booking.credit_movements.filter(
            kind=CreditKind.BOOKING).order_by("pack_id"))

        credit_pack_ids = [charge.pack_id for charge in charges]
        packs = {
            pack.pk: pack
            for pack in (
                CreditPack.objects.select_for_update()
                .filter(pk__in=credit_pack_ids)
                .order_by("pk")
            )
        }
        for charge in charges:
            pack = packs[charge.pack_id]
            refund_amount = -charge.amount
            pack.credits_remaining += refund_amount
            pack.save(update_fields=["credits_remaining"])
            CreditMovement.objects.create(
                pack=pack,
                booking=booking,
                kind=CreditKind.REFUND,
                amount=refund_amount,
                effective_at=now
            )

    promote_waitlist_entry(class_session_id=booking.class_session_id)
    return True


def is_waitlist_eligible(member, class_session: ClassSessions):
    now = timezone.now()
    if class_session.starts_at <= now:
        raise ClassAlreadyStarted()
    confirmed_seats_count = class_session.bookings.filter(
        status=BookingStatus.CONFIRMED
    ).count()
    if class_session.capacity > confirmed_seats_count:
        raise serializers.ValidationError(
            "Seats are available, no need to join waitlist")
    elif class_session.bookings.filter(
        member=member,
        status=BookingStatus.CONFIRMED
    ).exists():
        raise serializers.ValidationError(
            "You are already booked for this class")
    elif WaitlistEntry.objects.filter(
        member=member,
        class_session=class_session,
        status=EntryStatus.WAITING
    ).exists():
        raise serializers.ValidationError(
            "You are already on the waitlist for this class"
        )
    return True


@transaction.atomic
def join_waitlist(member, class_session_id):
    get_user_model().objects.select_for_update(no_key=True).get(pk=member.pk)
    class_session = get_object_or_404(
        ClassSessions.objects.select_for_update(),
        pk=class_session_id
    )
    is_waitlist_eligible(member, class_session)
    return WaitlistEntry.objects.create(
        member=member,
        class_session=class_session,
        status=EntryStatus.WAITING
    )


@transaction.atomic
def promote_waitlist_entry(class_session_id):
    class_session = get_object_or_404(
        ClassSessions.objects.select_for_update(), pk=class_session_id)
    waiting_list = (
        WaitlistEntry.objects.select_for_update()
        .filter(class_session=class_session_id, status=EntryStatus.WAITING)
        .order_by("joined_at", "pk")
    )
    for entry in waiting_list:
        try:
            check_class_availability(class_session)
            if Booking.objects.filter(
                member_id=entry.member_id,
                status=BookingStatus.CONFIRMED,
                class_session=class_session
            ).exists():
                continue
            booking = _create_booking(entry.member_id, class_session)
            entry.status = EntryStatus.PROMOTED
            entry.promoted_at = timezone.now()
            entry.booking = booking
            entry.save(update_fields=["status", "promoted_at", "booking"])
        except InsufficientCredits:
            continue
        except (NoSeatsAvailable, ClassAlreadyStarted):
            break
