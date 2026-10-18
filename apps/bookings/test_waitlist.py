"""Waitlist eligibility, queue order, charging, and transaction rollback."""

from datetime import timedelta
from unittest.mock import patch

from django.http import Http404
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.bookings.exceptions import ClassAlreadyStarted, InsufficientCredits
from apps.bookings.models import Booking, EntryStatus, WaitlistEntry
from apps.bookings.services import (
    book_class,
    cancel_booking,
    join_waitlist,
    promote_waitlist_entry,
    withdraw_waitlist_entry,
)
from apps.studios.models import CreditMovement
from apps.testing import DomainFixtures


class WaitlistServiceTests(DomainFixtures, TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.session.capacity = 1
        self.session.save()
        self.owner_pack = self.make_pack(member=self.other_member)
        body, _ = book_class(self.other_member, self.session.pk, "owner")
        self.owner_booking_id = body["id"]

    def test_join_full_class_needs_no_credits_and_does_not_charge(self) -> None:
        entry = join_waitlist(self.member, self.session.pk)
        self.assertEqual(entry.status, EntryStatus.WAITING)
        self.assertEqual(entry.member_id, self.member.pk)
        self.assertEqual(entry.class_session_id, self.session.pk)
        self.assertFalse(CreditMovement.objects.filter(pack__member=self.member).exists())
        self.assertEqual(Booking.objects.count(), 1)

    def test_join_rejects_available_started_missing_and_already_booked_classes(
        self,
    ) -> None:
        with self.assertRaises(ValidationError):
            join_waitlist(self.member, self.make_session().pk)
        with self.assertRaises(ClassAlreadyStarted):
            join_waitlist(
                self.member, self.make_session(starts_at=self.now - timedelta(1)).pk
            )
        with self.assertRaises(Http404):
            join_waitlist(self.member, 999999)
        with self.assertRaises(ValidationError):
            join_waitlist(self.other_member, self.session.pk)
        self.assertFalse(WaitlistEntry.objects.exists())

    def test_duplicate_join_rejected_and_withdrawal_allows_fresh_entry(self) -> None:
        entry = join_waitlist(self.member, self.session.pk)
        with self.assertRaises(ValidationError):
            join_waitlist(self.member, self.session.pk)
        withdraw_waitlist_entry(self.member, self.session.pk)
        replacement = join_waitlist(self.member, self.session.pk)
        entry.refresh_from_db()
        self.assertEqual(entry.status, EntryStatus.WITHDRAWN)
        self.assertNotEqual(replacement.pk, entry.pk)
        self.assertEqual(replacement.status, EntryStatus.WAITING)

    def test_cancellation_promotes_and_charges_earliest_affordable_waiter(self) -> None:
        pack = self.make_pack(credits=5)
        first = join_waitlist(self.member, self.session.pk)
        later = User.objects.create_user(username="later")
        self.make_pack(member=later)
        second = join_waitlist(later, self.session.pk)
        # Equal join times must still use entry ID as the queue tiebreaker.
        WaitlistEntry.objects.update(joined_at=self.now)
        cancel_booking(self.other_member, self.owner_booking_id)
        first.refresh_from_db()
        second.refresh_from_db()
        pack.refresh_from_db()
        self.assertEqual(first.status, EntryStatus.PROMOTED)
        self.assertIsNotNone(first.promoted_at)
        assert first.booking_id is not None
        booking = Booking.objects.get(pk=first.booking_id)
        self.assertEqual(booking.member_id, self.member.pk)
        self.assertEqual(booking.class_session_id, self.session.pk)
        self.assertEqual(booking.credits_charged, 3)
        self.assertEqual(pack.credits_remaining, 2)
        charge = CreditMovement.objects.get(booking=booking, kind="booking")
        self.assertEqual((charge.pack_id, charge.amount), (pack.pk, -3))
        self.assertEqual(second.status, EntryStatus.WAITING)
        self.assertEqual(self.session.bookings.filter(status="confirmed").count(), 1)

    def test_unaffordable_waiter_keeps_position_and_is_promoted_after_later_grant(
        self,
    ) -> None:
        first = join_waitlist(self.member, self.session.pk)
        original_joined_at = first.joined_at
        later = User.objects.create_user(username="later")
        self.make_pack(member=later)
        second = join_waitlist(later, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, EntryStatus.WAITING)
        self.assertEqual(first.joined_at, original_joined_at)
        self.assertEqual(second.status, EntryStatus.PROMOTED)
        self.make_pack(credits=3)
        assert second.booking_id is not None
        cancel_booking(later, second.booking_id)
        first.refresh_from_db()
        self.assertEqual(first.status, EntryStatus.PROMOTED)
        self.assertEqual(first.joined_at, original_joined_at)

    def test_withdrawn_waiter_is_not_promoted(self) -> None:
        self.make_pack()
        entry = join_waitlist(self.member, self.session.pk)
        withdraw_waitlist_entry(self.member, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        entry.refresh_from_db()
        self.assertEqual(entry.status, EntryStatus.WITHDRAWN)
        self.assertFalse(self.session.bookings.filter(status="confirmed").exists())

    def test_no_affordable_waiter_leaves_seat_available(self) -> None:
        entry = join_waitlist(self.member, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        entry.refresh_from_db()
        self.assertEqual(entry.status, EntryStatus.WAITING)
        self.assertFalse(self.session.bookings.filter(status="confirmed").exists())

    def test_started_class_does_not_promote_or_charge_waiter(self) -> None:
        pack = self.make_pack()
        entry = join_waitlist(self.member, self.session.pk)
        with patch(
            "apps.bookings.services.timezone.now", return_value=self.session.starts_at
        ):
            cancel_booking(self.other_member, self.owner_booking_id)
        entry.refresh_from_db()
        pack.refresh_from_db()
        self.assertEqual(entry.status, EntryStatus.WAITING)
        self.assertEqual(pack.credits_remaining, 10)
        self.assertFalse(self.session.bookings.filter(status="confirmed").exists())

    def test_repeated_promotion_of_full_class_does_not_charge_again(self) -> None:
        self.make_pack()
        join_waitlist(self.member, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        promote_waitlist_entry(self.session.pk)
        self.assertEqual(Booking.objects.filter(member=self.member).count(), 1)
        self.assertEqual(CreditMovement.objects.filter(kind="booking").count(), 2)

    def test_promotion_failure_rolls_back_cancellation_refund_and_charge(self) -> None:
        pack = self.make_pack()
        entry = join_waitlist(self.member, self.session.pk)
        movement_count = CreditMovement.objects.count()
        with (
            patch.object(
                WaitlistEntry, "save", side_effect=RuntimeError("write failed")
            ),
            self.assertRaises(RuntimeError),
        ):
            cancel_booking(self.other_member, self.owner_booking_id)
        owner_booking = Booking.objects.get(pk=self.owner_booking_id)
        self.owner_pack.refresh_from_db()
        pack.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(owner_booking.status, "confirmed")
        self.assertIsNone(owner_booking.cancelled_at)
        self.assertEqual(self.owner_pack.credits_remaining, 7)
        self.assertEqual(pack.credits_remaining, 10)
        self.assertEqual(entry.status, EntryStatus.WAITING)
        self.assertIsNone(entry.booking_id)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(CreditMovement.objects.count(), movement_count)

    def test_direct_booking_closes_waitlist_and_cancellation_does_not_rebook(
        self,
    ) -> None:
        entry = join_waitlist(self.member, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        pack = self.make_pack()
        body, _ = book_class(self.member, self.session.pk, "direct")
        entry.refresh_from_db()
        self.assertEqual(entry.status, EntryStatus.WITHDRAWN)
        self.assertIsNotNone(entry.withdrawn_at)
        self.assertIsNone(entry.booking_id)
        cancel_booking(self.member, body["id"])
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 10)
        self.assertFalse(self.session.bookings.filter(status="confirmed").exists())
        self.assertEqual(Booking.objects.filter(member=self.member).count(), 1)

    def test_failed_direct_booking_keeps_waiting_entry(self) -> None:
        entry = join_waitlist(self.member, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        with self.assertRaises(InsufficientCredits):
            book_class(self.member, self.session.pk, "cannot-pay")
        entry.refresh_from_db()
        self.assertEqual(entry.status, EntryStatus.WAITING)
        self.assertIsNone(entry.withdrawn_at)

    def test_idempotency_write_failure_restores_waitlist_and_credits(self) -> None:
        entry = join_waitlist(self.member, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        pack = self.make_pack()
        with (
            patch(
                "apps.bookings.services.IdempotencyRecord.objects.create",
                side_effect=RuntimeError("write failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            book_class(self.member, self.session.pk, "rollback")
        entry.refresh_from_db()
        pack.refresh_from_db()
        self.assertEqual(entry.status, EntryStatus.WAITING)
        self.assertIsNone(entry.withdrawn_at)
        self.assertEqual(pack.credits_remaining, 10)
        self.assertFalse(Booking.objects.filter(member=self.member).exists())

    def test_join_time_takes_priority_over_entry_id(self) -> None:
        self.make_pack()
        first = join_waitlist(self.member, self.session.pk)
        earlier = User.objects.create_user(username="earlier")
        self.make_pack(member=earlier)
        second = join_waitlist(earlier, self.session.pk)
        WaitlistEntry.objects.filter(pk=second.pk).update(
            joined_at=first.joined_at - timedelta(seconds=1)
        )
        cancel_booking(self.other_member, self.owner_booking_id)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, EntryStatus.WAITING)
        self.assertEqual(second.status, EntryStatus.PROMOTED)

    def test_replaying_old_booking_does_not_withdraw_a_new_waitlist_entry(self) -> None:
        join_waitlist(self.member, self.session.pk)
        cancel_booking(self.other_member, self.owner_booking_id)
        self.make_pack()
        original, _ = book_class(self.member, self.session.pk, "direct")
        cancel_booking(self.member, original["id"])
        book_class(self.other_member, self.session.pk, "owner-again")
        entry = join_waitlist(self.member, self.session.pk)
        replay, _ = book_class(self.member, self.session.pk, "direct")
        entry.refresh_from_db()
        self.assertEqual(replay, original)
        self.assertEqual(entry.status, EntryStatus.WAITING)
        self.assertIsNone(entry.withdrawn_at)
