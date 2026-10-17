from datetime import timedelta
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import book_class, cancel_booking
from apps.bookings.views import CancelBookingAPI
from apps.studios.models import CreditKind, CreditMovement
from apps.testing import DomainFixtures


class CancellationTests(DomainFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.pack = self.make_pack()
        body, _ = book_class(self.member, self.session.pk, "setup")
        self.booking = Booking.objects.get(pk=body["id"])

    def refunds(self):
        return CreditMovement.objects.filter(kind=CreditKind.REFUND)

    def test_early_cancellation_restores_credits_and_records_refund(self):
        self.assertTrue(cancel_booking(self.member, self.booking.pk))
        self.booking.refresh_from_db()
        self.pack.refresh_from_db()
        self.assertEqual(self.booking.status, BookingStatus.CANCELLED)
        self.assertIsNotNone(self.booking.cancelled_at)
        self.assertEqual(self.pack.credits_remaining, 10)
        refund = self.refunds().get()
        self.assertEqual(
            (refund.pack_id, refund.booking_id, refund.amount),
            (self.pack.pk, self.booking.pk, 3),
        )
        self.assertEqual(refund.effective_at, self.booking.cancelled_at)
        self.assertFalse(
            self.session.bookings.filter(status=BookingStatus.CONFIRMED).exists()
        )

    def test_exact_cutoff_refunds_but_one_microsecond_later_forfeits(self):
        for offset, expected in [(timedelta(0), 10), (timedelta(microseconds=1), 7)]:
            # Roll back each case so both start with a confirmed booking.
            with self.subTest(offset=offset), transaction.atomic():
                with patch(
                    "apps.bookings.services.timezone.now",
                    return_value=self.booking.cancellation_deadline + offset,
                ):
                    cancel_booking(self.member, self.booking.pk)
                self.pack.refresh_from_db()
                self.assertEqual(self.pack.credits_remaining, expected)
                self.assertEqual(self.refunds().count(), int(expected == 10))
                transaction.set_rollback(True)

    def test_repeat_cancellation_does_not_refund_twice(self):
        cancel_booking(self.member, self.booking.pk)
        with self.assertRaises(ValidationError):
            cancel_booking(self.member, self.booking.pk)
        self.pack.refresh_from_db()
        self.assertEqual(self.pack.credits_remaining, 10)
        self.assertEqual(self.refunds().count(), 1)

    def test_refund_failure_rolls_back_status_balance_and_movements(self):
        with (
            patch(
                "apps.bookings.services.CreditMovement.objects.create",
                side_effect=RuntimeError("write failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            cancel_booking(self.member, self.booking.pk)
        self.booking.refresh_from_db()
        self.pack.refresh_from_db()
        self.assertEqual(self.booking.status, BookingStatus.CONFIRMED)
        self.assertIsNone(self.booking.cancelled_at)
        self.assertEqual(self.pack.credits_remaining, 7)
        self.assertFalse(self.refunds().exists())

    def test_refund_to_expired_pack_preserves_expiry(self):
        expiry = self.now - timedelta(seconds=1)
        self.pack.expires_at = expiry
        self.pack.save(update_fields=["expires_at"])
        cancel_booking(self.member, self.booking.pk)
        self.pack.refresh_from_db()
        self.assertEqual(self.pack.credits_remaining, 10)
        self.assertEqual(self.pack.expires_at, expiry)

    def post(self, user, booking_id=None):
        request = APIRequestFactory().post("/cancel", {}, format="json")
        if user is not None:
            force_authenticate(request, user=user)
        return CancelBookingAPI.as_view()(
            request, booking_id=booking_id or self.booking.pk
        )

    def test_direct_view_success(self):
        self.assertEqual(self.post(self.member).status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, BookingStatus.CANCELLED)

    def test_other_member_and_missing_booking_are_404(self):
        self.assertEqual(self.post(self.other_member).status_code, 404)
        self.assertEqual(self.post(self.member, 999999).status_code, 404)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, BookingStatus.CONFIRMED)
        self.assertFalse(self.refunds().exists())

    def test_anonymous_is_401(self):
        self.assertEqual(self.post(None).status_code, 401)

    def test_repeat_request_is_400(self):
        self.assertEqual(self.post(self.member).status_code, 200)
        self.assertEqual(self.post(self.member).status_code, 400)
        self.assertEqual(self.refunds().count(), 1)

    def test_registered_cancellation_route(self):
        client = APIClient()
        client.force_authenticate(self.member)
        response = client.post(f"/bookings/{self.booking.pk}/cancel", {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, BookingStatus.CANCELLED)


class CancellationAllocationTests(DomainFixtures, TestCase):
    def test_multiple_packs_receive_their_original_allocations(self):
        first = self.make_pack(credits=1, expires_at=self.now + timedelta(days=4))
        second = self.make_pack(credits=5)
        untouched = self.make_pack(credits=8, expires_at=self.now + timedelta(days=40))
        body, _ = book_class(self.member, self.session.pk, "split")
        cancel_booking(self.member, body["id"])
        for pack, expected in [(first, 1), (second, 5), (untouched, 8)]:
            pack.refresh_from_db()
            self.assertEqual(pack.credits_remaining, expected)
        self.assertEqual(
            dict(
                CreditMovement.objects.filter(kind=CreditKind.REFUND).values_list(
                    "pack_id", "amount"
                )
            ),
            {first.pk: 1, second.pk: 2},
        )

    def test_free_booking_cancels_without_credit_movements(self):
        self.session.credit_cost = 0
        self.session.save(update_fields=["credit_cost"])
        body, _ = book_class(self.member, self.session.pk, "free")
        self.assertTrue(cancel_booking(self.member, body["id"]))
        self.assertFalse(CreditMovement.objects.exists())
