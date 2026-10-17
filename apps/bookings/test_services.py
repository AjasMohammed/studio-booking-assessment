from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import IntegrityError
from django.http import Http404
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.bookings.models import Booking, BookingStatus, IdempotencyRecord
from apps.bookings.services import IdempotencyConflict, book_class
from apps.studios.models import CreditKind, CreditMovement, CreditPack, Studio
from apps.testing import DomainFixtures


class BookingServiceTests(DomainFixtures, TestCase):
    def book(self, key="request-1", session=None, member=None):
        return book_class(member or self.member, (session or self.session).pk, key)

    def assert_no_booking_writes(self):
        self.assertFalse(Booking.objects.exists())
        self.assertFalse(IdempotencyRecord.objects.exists())
        self.assertFalse(
            CreditMovement.objects.filter(kind=CreditKind.BOOKING).exists()
        )

    def test_booking_charges_and_records_exact_cost(self):
        pack = self.make_pack()
        body, status = self.book()
        pack.refresh_from_db()
        booking = Booking.objects.get(pk=body["id"])
        movement = booking.credit_movements.get()
        self.assertEqual(status, 201)
        self.assertEqual(pack.credits_remaining, 7)
        self.assertEqual(movement.amount, -3)
        self.assertEqual(booking.credits_charged, 3)
        self.assertEqual(movement.pack_id, pack.pk)
        self.assertEqual(IdempotencyRecord.objects.get().response_body, body)

    def test_spends_earliest_expiry_even_if_created_last(self):
        later = self.make_pack(5, expires_at=self.now + timedelta(days=20))
        earlier = self.make_pack(2, expires_at=self.now + timedelta(days=10))
        self.session.credit_cost = 4
        self.session.save()
        body, _ = self.book()
        earlier.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual((earlier.credits_remaining, later.credits_remaining), (0, 3))
        self.assertCountEqual(
            CreditMovement.objects.filter(booking_id=body["id"]).values_list(
                "pack_id", "amount"
            ),
            [(earlier.pk, -2), (later.pk, -2)],
        )

    def test_spends_only_needed_amount_across_three_packs(self):
        for index, amount in enumerate([2, 3, 5]):
            self.make_pack(amount, expires_at=self.now + timedelta(days=index + 1))
        self.session.credit_cost = 6
        self.session.save()
        self.book()
        self.assertEqual(
            list(
                CreditPack.objects.order_by("expires_at", "pk").values_list(
                    "credits_remaining", flat=True
                )
            ),
            [0, 0, 4],
        )

    def test_equal_expiries_use_primary_key_as_tiebreaker(self):
        first = self.make_pack(3)
        second = self.make_pack(3)
        self.book()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.credits_remaining, second.credits_remaining), (0, 3))

    def test_zero_balance_pack_is_skipped(self):
        self.make_pack(0, expires_at=self.now + timedelta(days=1))
        self.make_pack(3)
        self.book()
        self.assertEqual(CreditMovement.objects.filter(kind="booking").count(), 1)

    def test_exact_balance_can_be_fully_spent(self):
        pack = self.make_pack(3)
        self.book()
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 0)

    def test_insufficient_credits_leave_everything_unchanged(self):
        pack = self.make_pack(2)
        with self.assertRaises(ValidationError):
            self.book()
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 2)
        self.assert_no_booking_writes()

    def test_no_packs_rejects_paid_booking(self):
        with self.assertRaises(ValidationError):
            self.book()
        self.assert_no_booking_writes()

    def test_other_member_and_studio_credits_cannot_be_spent(self):
        other_studio = Studio.objects.create(name="Pilates")
        self.make_pack(10, member=self.other_member)
        self.make_pack(10, studio=other_studio)
        with self.assertRaises(ValidationError):
            self.book()
        self.assert_no_booking_writes()
        self.assertEqual(
            set(CreditPack.objects.values_list("credits_remaining", flat=True)), {10}
        )

    def test_expired_exactly_expiring_and_future_grants_are_excluded(self):
        self.make_pack(10, expires_at=self.now - timedelta(seconds=1))
        self.make_pack(10, expires_at=self.now)
        self.make_pack(10, granted_at=self.now + timedelta(seconds=1))
        with (
            patch("apps.bookings.services.timezone.now", return_value=self.now),
            self.assertRaises(ValidationError),
        ):
            self.book()
        self.assert_no_booking_writes()

    def test_pack_is_usable_exactly_at_grant_time(self):
        self.make_pack(3, granted_at=self.now)
        with patch("apps.bookings.services.timezone.now", return_value=self.now):
            self.assertEqual(self.book()[1], 201)

    def test_started_class_rejects_without_charging(self):
        self.make_pack()
        for delta in [timedelta(seconds=-1), timedelta(0)]:
            with self.subTest(delta=delta):
                self.session.starts_at = self.now + delta
                self.session.save()
                with (
                    patch("apps.bookings.services.timezone.now", return_value=self.now),
                    self.assertRaises(ValidationError),
                ):
                    self.book()
                self.assert_no_booking_writes()

    def test_missing_class_is_404(self):
        with self.assertRaises(Http404):
            book_class(self.member, 999999, "missing")
        self.assert_no_booking_writes()

    def test_full_class_rejects_without_charge(self):
        self.make_pack()
        self.make_pack(member=self.other_member)
        self.session.capacity = 1
        self.session.save()
        self.book(member=self.other_member)
        before = list(
            CreditPack.objects.order_by("pk").values_list(
                "credits_remaining", flat=True
            )
        )
        with self.assertRaises(ValidationError):
            self.book()
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(
            before,
            list(
                CreditPack.objects.order_by("pk").values_list(
                    "credits_remaining", flat=True
                )
            ),
        )

    def test_cancelled_booking_does_not_consume_capacity(self):
        self.make_pack()
        Booking.objects.create(
            member=self.other_member,
            class_session=self.session,
            status=BookingStatus.CANCELLED,
            cancelled_at=self.now,
            credits_charged=3,
            cancellation_deadline=self.now,
        )
        self.session.capacity = 1
        self.session.save()
        self.assertEqual(self.book()[1], 201)

    def test_free_class_needs_no_pack_or_zero_value_movement(self):
        self.session.credit_cost = 0
        self.session.save()
        body, _ = self.book()
        self.assertEqual(body["credits_charged"], 0)
        self.assertFalse(CreditMovement.objects.exists())

    def test_retry_replays_response_even_when_last_seat_is_full(self):
        pack = self.make_pack(3)
        self.session.capacity = 1
        self.session.save()
        original = self.book()
        self.assertEqual(self.book(), original)
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 0)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(CreditMovement.objects.filter(kind="booking").count(), 1)

    def test_retry_after_class_started_replays_original_response(self):
        self.make_pack()
        original = self.book()
        self.session.starts_at = self.now - timedelta(days=1)
        self.session.save()
        self.assertEqual(self.book(), original)

    def test_retry_after_cancellation_does_not_create_new_booking(self):
        self.make_pack()
        original = self.book()
        Booking.objects.filter(pk=original[0]["id"]).update(
            status="cancelled", cancelled_at=self.now
        )
        self.assertEqual(self.book(), original)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(CreditMovement.objects.filter(kind="booking").count(), 1)

    def test_new_key_after_cancellation_can_create_a_new_booking(self):
        pack = self.make_pack()
        original, _ = self.book()
        Booking.objects.filter(pk=original["id"]).update(
            status="cancelled", cancelled_at=self.now
        )
        replacement, status = self.book(key="new-booking-attempt")
        self.assertEqual(status, 201)
        self.assertNotEqual(replacement["id"], original["id"])
        self.assertEqual(IdempotencyRecord.objects.count(), 2)
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 4)

    def test_reusing_key_for_another_class_is_conflict(self):
        self.make_pack()
        self.book()
        other_class = self.make_session()
        with self.assertRaises(IdempotencyConflict):
            self.book(session=other_class)
        self.assertEqual(Booking.objects.count(), 1)

    def test_different_members_may_use_same_key(self):
        self.make_pack()
        self.make_pack(member=self.other_member)
        self.book()
        self.book(member=self.other_member)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)

    def test_new_key_does_not_double_charge_existing_confirmed_booking(self):
        pack = self.make_pack()
        self.book()
        with self.assertRaises(ValidationError):
            self.book(key="another-key")
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 7)
        self.assertEqual(Booking.objects.count(), 1)

    def test_invalid_keys_are_rejected_without_writes(self):
        self.make_pack()
        for key in [None, "", "   ", "a" * 256]:
            with self.subTest(key=key), self.assertRaises(ValidationError):
                self.book(key=key)
            self.assert_no_booking_writes()

    def test_maximum_key_length_is_accepted(self):
        self.make_pack()
        self.assertEqual(self.book(key="a" * 255)[1], 201)

    def test_failed_attempt_can_retry_with_same_key_after_grant(self):
        with self.assertRaises(ValidationError):
            self.book()
        self.assert_no_booking_writes()
        self.make_pack()
        self.assertEqual(self.book()[1], 201)

    def test_second_debit_failure_rolls_back_all_allocations(self):
        first = self.make_pack(2, expires_at=self.now + timedelta(days=1))
        second = self.make_pack(5)
        create = CreditMovement.objects.create
        calls = []

        def fail_second_debit(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise IntegrityError("simulated second debit failure")
            return create(**kwargs)

        with (
            patch(
                "apps.bookings.services.CreditMovement.objects.create",
                side_effect=fail_second_debit,
            ),
            self.assertRaises(IntegrityError),
        ):
            self.book()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.credits_remaining, second.credits_remaining), (2, 5))
        self.assert_no_booking_writes()

    def test_idempotency_save_failure_rolls_back_booking_and_charge(self):
        pack = self.make_pack()
        with (
            patch(
                "apps.bookings.services.IdempotencyRecord.objects.create",
                side_effect=IntegrityError("simulated outcome failure"),
            ),
            self.assertRaises(IntegrityError),
        ):
            self.book()
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 10)
        self.assert_no_booking_writes()

    def test_cutoff_is_captured_from_class_start_not_booking_time(self):
        self.make_pack()
        body, _ = self.book()
        self.assertEqual(
            Booking.objects.get(pk=body["id"]).cancellation_deadline,
            self.session.starts_at - timedelta(hours=4),
        )

    def test_zero_cutoff_deadline_is_class_start(self):
        self.make_pack()
        self.studio.cancellation_cutoff_hours = 0
        self.studio.save()
        body, _ = self.book()
        self.assertEqual(
            Booking.objects.get(pk=body["id"]).cancellation_deadline,
            self.session.starts_at,
        )

    def test_cutoff_uses_studio_local_clock_across_dst(self):
        # Both local deadlines below exist unambiguously: this tests wall-clock policy.
        self.make_pack()
        zone = ZoneInfo("America/New_York")
        self.studio.timezone = zone.key
        self.studio.save()
        for starts_at in [
            datetime(2027, 3, 14, 7, 30, tzinfo=UTC),
            datetime(2027, 11, 7, 6, 30, tzinfo=UTC),
        ]:
            with self.subTest(starts_at=starts_at):
                session = self.make_session(starts_at=starts_at, credit_cost=0)
                with patch(
                    "apps.bookings.services.timezone.now",
                    return_value=datetime(2027, 1, 1, tzinfo=UTC),
                ):
                    body, _ = self.book(key=starts_at.isoformat(), session=session)
                actual = Booking.objects.get(pk=body["id"]).cancellation_deadline
                expected = starts_at.astimezone(zone) - timedelta(hours=4)
                self.assertEqual(actual.astimezone(UTC), expected.astimezone(UTC))

    def test_dst_deadline_policy_for_ambiguous_and_nonexistent_local_times(self):
        self.studio.timezone = "America/New_York"
        self.studio.cancellation_cutoff_hours = 1
        self.studio.save()
        # Missing 02:30 shifts forward; repeated 01:30 uses its first occurrence.
        for start, expected in [
            (
                datetime(2027, 3, 14, 7, 30, tzinfo=UTC),
                datetime(2027, 3, 14, 7, 30, tzinfo=UTC),
            ),
            (
                datetime(2027, 11, 7, 7, 30, tzinfo=UTC),
                datetime(2027, 11, 7, 5, 30, tzinfo=UTC),
            ),
        ]:
            with self.subTest(start=start):
                session = self.make_session(starts_at=start, credit_cost=0)
                with patch(
                    "apps.bookings.services.timezone.now",
                    return_value=datetime(2027, 1, 1, tzinfo=UTC),
                ):
                    body, _ = self.book(key=start.isoformat(), session=session)
                self.assertEqual(
                    Booking.objects.get(pk=body["id"]).cancellation_deadline, expected
                )

    def test_zero_cutoff_during_repeated_hour_keeps_exact_start_instant(self):
        self.studio.timezone = "America/New_York"
        self.studio.cancellation_cutoff_hours = 0
        self.studio.save()
        start = datetime(2027, 11, 7, 6, 30, tzinfo=UTC)
        session = self.make_session(starts_at=start, credit_cost=0)
        with patch(
            "apps.bookings.services.timezone.now",
            return_value=datetime(2027, 1, 1, tzinfo=UTC),
        ):
            body, _ = self.book(session=session)
        self.assertEqual(
            Booking.objects.get(pk=body["id"]).cancellation_deadline, start
        )
