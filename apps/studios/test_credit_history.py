"""Regression coverage for calculated expiry events and accounting boundaries."""

from datetime import datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import book_class, cancel_booking
from apps.studios.models import CreditKind, CreditMovement, CreditPack
from apps.testing import DomainFixtures


class CreditExpiryHistoryTests(DomainFixtures, TestCase):
    client: APIClient
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.client.force_authenticate(self.member)
        self.url = reverse("credit_movements")
        self.expiry = self.now - timedelta(hours=6)

    def make_history(
        self, cost: int = 3, refund_at: datetime | None = None
    ) -> CreditPack:
        """Create a real charge before expiry and optionally refund it afterward."""
        pack = self.make_pack(10, expires_at=self.expiry)
        self.session.credit_cost = cost
        self.session.save(update_fields=["credit_cost"])
        with patch(
            "apps.bookings.services.timezone.now",
            return_value=self.now - timedelta(hours=12),
        ):
            body, _ = book_class(self.member, self.session.pk, "expiry-history")
        if refund_at is not None:
            with patch("apps.bookings.services.timezone.now", return_value=refund_at):
                cancel_booking(self.member, body["id"])
        return pack

    def events(self) -> list[dict[str, Any]]:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return cast(list[dict[str, Any]], response.data)

    def test_partially_spent_pack_expires_only_its_remaining_credits(self) -> None:
        pack = self.make_history()
        events = self.events()
        self.assertEqual(
            [(event["kind"], event["amount"]) for event in events],
            [("grant", 10), ("booking", -3), ("expiry", -7)],
        )
        expiry = events[-1]
        self.assertIsNone(expiry["id"])
        self.assertIsNone(expiry["booking_id"])
        self.assertIsNone(expiry["recorded_at"])
        self.assertEqual(expiry["pack_id"], pack.pk)
        self.assertEqual(expiry["studio"]["id"], self.studio.pk)
        self.assertEqual(sum(event["amount"] for event in events), 0)

    def test_fully_spent_pack_has_no_zero_value_expiry(self) -> None:
        self.make_history(cost=10)
        self.assertEqual(
            [event["kind"] for event in self.events()], ["grant", "booking"]
        )

    def test_refund_before_expiry_increases_the_original_expiry_amount(self) -> None:
        self.make_history(refund_at=self.expiry - timedelta(hours=1))
        self.assertEqual(
            [(event["kind"], event["amount"]) for event in self.events()],
            [("grant", 10), ("booking", -3), ("refund", 3), ("expiry", -10)],
        )

    def test_refund_after_expiry_receives_a_matching_expiry(self) -> None:
        pack = self.make_history(refund_at=self.expiry + timedelta(hours=1))
        events = self.events()
        self.assertEqual(
            [(event["kind"], event["amount"]) for event in events],
            [
                ("grant", 10),
                ("booking", -3),
                ("expiry", -7),
                ("refund", 3),
                ("expiry", -3),
            ],
        )
        self.assertEqual(events[-2]["effective_at"], events[-1]["effective_at"])
        self.assertEqual(sum(event["amount"] for event in events), 0)
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 10)
        self.assertEqual(
            self.client.get(reverse("credit_balance")).data, {"studios": []}
        )

    def test_refund_exactly_at_expiry_follows_original_expiry(self) -> None:
        self.make_history(refund_at=self.expiry)
        events = self.events()
        self.assertEqual(
            [(event["kind"], event["amount"]) for event in events[-3:]],
            [("expiry", -7), ("refund", 3), ("expiry", -3)],
        )
        self.assertEqual(len({event["effective_at"] for event in events[-3:]}), 1)

    def test_future_expiries_and_future_movements_are_not_reported(self) -> None:
        pack = self.make_pack(10)
        self.make_pack(5, granted_at=self.now + timedelta(days=1))
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "grant")
        self.assertEqual(events[0]["pack_id"], pack.pk)

    def test_exact_expiry_is_included_but_not_one_microsecond_before(self) -> None:
        pack = self.make_pack(10, expires_at=self.now)
        with patch(
            "apps.studios.services.timezone.now",
            return_value=pack.expires_at - timedelta(microseconds=1),
        ):
            self.assertEqual([event["kind"] for event in self.events()], ["grant"])
        with patch("apps.studios.services.timezone.now", return_value=pack.expires_at):
            self.assertEqual(
                [event["kind"] for event in self.events()], ["grant", "expiry"]
            )

    def test_multiple_packs_expire_independently_without_exposing_others(self) -> None:
        first = self.make_pack(10, expires_at=self.expiry)
        second = self.make_pack(4, expires_at=self.expiry + timedelta(hours=1))
        self.make_pack(100, member=self.other_member, expires_at=self.expiry)
        expiries = [event for event in self.events() if event["kind"] == "expiry"]
        self.assertEqual(
            [(event["pack_id"], event["amount"]) for event in expiries],
            [(first.pk, -10), (second.pk, -4)],
        )

    def test_refunds_with_identical_timestamps_keep_their_expiries_adjacent(
        self,
    ) -> None:
        pack = self.make_pack(10, expires_at=self.expiry)
        refund_time = self.expiry + timedelta(hours=1)
        refunds = []
        for amount in [3, 2]:
            booking = Booking.objects.create(
                member=self.member,
                class_session=self.session,
                credits_charged=amount,
                status=BookingStatus.CANCELLED,
                cancelled_at=refund_time,
                cancellation_deadline=refund_time,
            )
            CreditMovement.objects.create(
                pack=pack,
                booking=booking,
                kind=CreditKind.BOOKING,
                amount=-amount,
                effective_at=self.expiry - timedelta(hours=1),
            )
            refunds.append(
                CreditMovement.objects.create(
                    pack=pack,
                    booking=booking,
                    kind=CreditKind.REFUND,
                    amount=amount,
                    effective_at=refund_time,
                )
            )
        pack.credits_remaining = 10
        pack.save(update_fields=["credits_remaining"])
        events = self.events()
        self.assertEqual(
            [(event["id"], event["amount"]) for event in events[-4:]],
            [(refunds[0].pk, 3), (None, -3), (refunds[1].pk, 2), (None, -2)],
        )

    def test_history_is_stable_read_only_and_uses_one_query(self) -> None:
        self.make_history(refund_at=self.expiry + timedelta(hours=1))
        original_movements = list(CreditMovement.objects.values().order_by("pk"))
        original_packs = list(CreditPack.objects.values().order_by("pk"))
        with self.assertNumQueries(1):
            first = self.events()
        with self.assertNumQueries(1):
            second = self.events()
        self.assertEqual(first, second)
        self.assertEqual(
            list(CreditMovement.objects.values().order_by("pk")), original_movements
        )
        self.assertEqual(
            list(CreditPack.objects.values().order_by("pk")), original_packs
        )
        self.assertFalse(CreditMovement.objects.filter(kind=CreditKind.EXPIRY).exists())
