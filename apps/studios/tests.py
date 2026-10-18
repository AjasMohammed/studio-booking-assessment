from datetime import UTC, datetime, timedelta
from datetime import timezone as datetime_timezone
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APITestCase

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import book_class, cancel_booking
from apps.studios.models import ClassSessions, CreditMovement, CreditPack, Studio
from apps.studios.services import grant_credit_pack
from apps.testing import DomainFixtures


class StudioAPITests(DomainFixtures, APITestCase):
    def test_studio_list_includes_studio_id(self) -> None:
        self.client.force_authenticate(self.staff)
        response = self.client.get(reverse("list_studios"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["id"], self.studio.pk)

    def test_studio_creation_requires_staff(self) -> None:
        url = reverse("create_studio")
        self.assertEqual(self.client.post(url, {"name": "New"}).status_code, 401)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(url, {"name": "New"}).status_code, 403)
        self.client.force_authenticate(self.staff)
        response = self.client.post(url, {"name": "New"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Studio.objects.filter(pk=response.data["studio_id"]).exists())

    def test_studio_rejects_bad_timezone_negative_cutoff_and_duplicate_name(
        self,
    ) -> None:
        self.client.force_authenticate(self.staff)
        for data in [
            {"name": "New", "timezone": "Not/A_Timezone"},
            {"name": "New", "cancellation_cutoff_hours": -1},
            {"name": self.studio.name},
        ]:
            with self.subTest(data=data):
                self.assertEqual(
                    self.client.post(
                        reverse("create_studio"), data, format="json"
                    ).status_code,
                    400,
                )

    def test_zero_cancellation_cutoff_is_allowed(self) -> None:
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.post(
                reverse("create_studio"),
                {
                    "name": "Immediate cutoff",
                    "cancellation_cutoff_hours": 0,
                },
                format="json",
            ).status_code,
            201,
        )

    def class_payload(self, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "starts_at": (self.now + timedelta(days=1)).isoformat(),
            "duration_minutes": 60,
            "capacity": 10,
            "credit_cost": 3,
        }
        data.update(overrides)
        return data

    def test_class_creation_links_url_studio_and_rejects_member(self) -> None:
        url = reverse("create_class_session", args=[self.studio.pk])
        self.client.force_authenticate(self.member)
        self.assertEqual(
            self.client.post(url, self.class_payload(), format="json").status_code, 403
        )
        self.client.force_authenticate(self.staff)
        response = self.client.post(url, self.class_payload(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            ClassSessions.objects.get(pk=response.data["session_id"]).studio_id,
            self.studio.pk,
        )

    def test_class_creation_unknown_studio_is_404(self) -> None:
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.post(
                reverse("create_class_session", args=[999999]),
                self.class_payload(),
                format="json",
            ).status_code,
            404,
        )

    def test_class_rejects_past_exact_now_and_malformed_start(self) -> None:
        self.client.force_authenticate(self.staff)
        for start in [
            self.now.isoformat(),
            (self.now - timedelta(seconds=1)).isoformat(),
            "not-a-date",
        ]:
            with (
                self.subTest(start=start),
                patch("apps.studios.validators.timezone.now", return_value=self.now),
            ):
                self.assertEqual(
                    self.client.post(
                        reverse("create_class_session", args=[self.studio.pk]),
                        self.class_payload(starts_at=start),
                        format="json",
                    ).status_code,
                    400,
                )

    def test_class_rejects_nonpositive_duration_capacity_and_negative_cost(
        self,
    ) -> None:
        self.client.force_authenticate(self.staff)
        for field, value in [
            ("duration_minutes", 0),
            ("duration_minutes", -1),
            ("capacity", 0),
            ("capacity", -1),
            ("credit_cost", -1),
        ]:
            with self.subTest(field=field, value=value):
                self.assertEqual(
                    self.client.post(
                        reverse("create_class_session", args=[self.studio.pk]),
                        self.class_payload(**{field: value}),
                        format="json",
                    ).status_code,
                    400,
                )

    def test_equivalent_offsets_save_same_start_instant(self) -> None:
        self.client.force_authenticate(self.staff)
        utc_start = (self.now + timedelta(days=1)).astimezone(UTC)
        india = datetime_timezone(timedelta(hours=5, minutes=30))
        saved = []
        for start in [utc_start, utc_start.astimezone(india)]:
            response = self.client.post(
                reverse("create_class_session", args=[self.studio.pk]),
                self.class_payload(starts_at=start.isoformat()),
                format="json",
            )
            self.assertEqual(response.status_code, 201)
            saved.append(ClassSessions.objects.get(pk=response.data["session_id"]))
        self.assertEqual(saved[0].starts_at, saved[1].starts_at)


class ClassBrowsingAPITests(DomainFixtures, APITestCase):
    def test_invalid_date_ranges_return_field_errors(self) -> None:
        self.client.force_authenticate(self.member)
        day = self.session.starts_at.date().isoformat()
        later = (self.session.starts_at.date() + timedelta(days=1)).isoformat()
        cases = [
            ({"start_date": "invalid", "end_date": day}, "start_date"),
            ({"start_date": day, "end_date": "invalid"}, "end_date"),
            ({"start_date": day}, "end_date"),
            ({"end_date": day}, "start_date"),
            ({"start_date": later, "end_date": day}, "end_date"),
        ]
        for params, field in cases:
            with self.subTest(params=params):
                response = self.client.get(reverse("list_class_sessions"), params)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.data)

    def test_class_list_requires_authentication(self) -> None:
        self.assertEqual(
            self.client.get(reverse("list_class_sessions")).status_code, 401
        )

    def test_registered_route_lists_future_classes_and_counts_confirmed_seats(
        self,
    ) -> None:
        url = reverse("list_class_sessions")
        self.assertEqual(url, "/studio/classes")
        self.make_session(starts_at=self.now - timedelta(days=1))
        Booking.objects.create(
            member=self.member,
            class_session=self.session,
            cancellation_deadline=self.now,
        )
        Booking.objects.create(
            member=self.other_member,
            class_session=self.session,
            status=BookingStatus.CANCELLED,
            cancelled_at=self.now,
            cancellation_deadline=self.now,
        )
        self.client.force_authenticate(self.member)

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.session.pk)
        self.assertEqual(response.data[0]["studio"]["id"], self.studio.pk)
        self.assertEqual(response.data[0]["no_of_seats_available"], 1)

    def test_class_list_accepts_date_range_through_registered_route(self) -> None:
        self.make_session(starts_at=self.now + timedelta(days=5))
        self.client.force_authenticate(self.member)
        day = self.session.starts_at.date().isoformat()

        response = self.client.get(
            reverse("list_class_sessions"),
            {"start_date": day, "end_date": day},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["no_of_seats_available"], 2)


class CreditAPITests(DomainFixtures, APITestCase):
    def grant_payload(self, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "member": self.member.pk,
            "credits_remaining": 10,
            "expires_at": (self.now + timedelta(days=30)).isoformat(),
        }
        data.update(overrides)
        return data

    def grant(self, **overrides: object) -> Response:
        return self.client.post(
            reverse("grant_credit_pack", args=[self.studio.pk]),
            self.grant_payload(**overrides),
            format="json",
        )

    def test_grant_requires_staff(self) -> None:
        self.assertEqual(self.grant().status_code, 401)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.grant().status_code, 403)
        self.assertFalse(CreditPack.objects.exists())

    def test_valid_grant_records_staff_amount_and_same_effective_time(self) -> None:
        self.client.force_authenticate(self.staff)
        response = self.grant()
        self.assertEqual(response.status_code, 201)
        pack = CreditPack.objects.get(pk=response.data["id"])
        movement = pack.movements.get()
        self.assertEqual(pack.granted_by_id, self.staff.pk)
        self.assertEqual(pack.studio_id, self.studio.pk)
        self.assertEqual(movement.amount, pack.credits_remaining)
        self.assertEqual(movement.effective_at, pack.granted_at)

    def test_each_grant_preserves_separate_pack_and_expiry(self) -> None:
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.grant().status_code, 201)
        self.assertEqual(
            self.grant(
                expires_at=(self.now + timedelta(days=60)).isoformat()
            ).status_code,
            201,
        )
        self.assertEqual(CreditPack.objects.count(), 2)
        self.assertEqual(CreditMovement.objects.filter(kind="grant").count(), 2)
        self.assertEqual(CreditPack.objects.values("expires_at").distinct().count(), 2)

    def test_grant_cannot_override_staff_or_url_studio(self) -> None:
        other_studio = Studio.objects.create(name="Other studio")
        self.client.force_authenticate(self.staff)
        response = self.grant(studio=other_studio.pk, granted_by=self.member.pk)
        self.assertEqual(response.status_code, 201)
        pack = CreditPack.objects.get(pk=response.data["id"])
        self.assertEqual(pack.studio_id, self.studio.pk)
        self.assertEqual(pack.granted_by_id, self.staff.pk)

    def test_grant_rejects_zero_negative_fractional_and_invalid_recipient(self) -> None:
        self.client.force_authenticate(self.staff)
        invalid_grants: list[dict[str, object]] = [
            {"credits_remaining": 0},
            {"credits_remaining": -1},
            {"credits_remaining": 1.5},
            {"member": self.staff.pk},
            {"member": 999999},
        ]
        for data in invalid_grants:
            with self.subTest(data=data):
                self.assertEqual(self.grant(**data).status_code, 400)
        self.assertFalse(CreditPack.objects.exists())
        self.assertFalse(CreditMovement.objects.exists())

    def test_grant_rejects_expiry_at_or_before_now(self) -> None:
        self.client.force_authenticate(self.staff)
        for expiry in [self.now, self.now - timedelta(seconds=1)]:
            with (
                self.subTest(expiry=expiry),
                patch("apps.studios.validators.timezone.now", return_value=self.now),
            ):
                self.assertEqual(
                    self.grant(expires_at=expiry.isoformat()).status_code, 400
                )

    def test_oversized_grant_returns_validation_error_not_server_error(self) -> None:
        self.client.force_authenticate(self.staff)
        self.client.raise_request_exception = False
        self.assertEqual(self.grant(credits_remaining=2**63).status_code, 400)
        self.assertFalse(CreditPack.objects.exists())

    def test_grant_unknown_studio_is_404(self) -> None:
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.post(
                reverse("grant_credit_pack", args=[999999]),
                self.grant_payload(),
                format="json",
            ).status_code,
            404,
        )

    def test_balance_groups_packs_and_excludes_others_expired_and_future(self) -> None:
        self.make_pack(2)
        self.make_pack(5, expires_at=self.now + timedelta(days=40))
        other_studio = Studio.objects.create(name="Pilates")
        self.make_pack(3, studio=other_studio)
        self.make_pack(50, member=self.other_member)
        self.make_pack(60, expires_at=self.now - timedelta(seconds=1))
        self.make_pack(70, granted_at=self.now + timedelta(days=1))
        self.client.force_authenticate(self.member)
        with self.assertNumQueries(2):
            response = self.client.get(reverse("credit_balance"))
        self.assertEqual(response.status_code, 200)
        studios = {row["id"]: row for row in response.data["studios"]}
        self.assertEqual(studios[self.studio.pk]["total_credits"], 7)
        self.assertEqual(studios[other_studio.pk]["total_credits"], 3)
        for row in studios.values():
            self.assertEqual(
                row["total_credits"],
                sum(p["credits_remaining"] for p in row["credit_packs"]),
            )

    def test_balance_respects_exact_grant_and_expiry_boundaries(self) -> None:
        self.make_pack(3, granted_at=self.now)
        self.make_pack(50, expires_at=self.now)
        self.client.force_authenticate(self.member)
        with patch("apps.studios.selectors.timezone.now", return_value=self.now):
            response = self.client.get(reverse("credit_balance"))
        self.assertEqual(response.data["studios"][0]["total_credits"], 3)

    def test_balance_requires_auth_and_empty_account_returns_empty_list(self) -> None:
        self.assertEqual(self.client.get(reverse("credit_balance")).status_code, 401)
        self.client.force_authenticate(self.member)
        self.assertEqual(
            self.client.get(reverse("credit_balance")).data, {"studios": []}
        )

    def test_balance_uses_authenticated_member_not_query_parameter(self) -> None:
        self.make_pack(80, member=self.other_member)
        self.client.force_authenticate(self.member)
        response = self.client.get(
            reverse("credit_balance"),
            {
                "member": self.other_member.pk,
            },
        )
        self.assertEqual(response.data, {"studios": []})

    def test_balance_reflects_booking_deductions(self) -> None:
        self.make_pack(10)
        book_class(self.member, self.session.pk, "book-for-balance")
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse("credit_balance"))
        self.assertEqual(response.data["studios"][0]["total_credits"], 7)


class HistoricalCreditBalanceAPITests(DomainFixtures, APITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.grant_time = self.now - timedelta(days=10)
        self.booking_time = self.now - timedelta(days=7)
        self.refund_time = self.now - timedelta(days=5)
        self.expiry_time = self.now - timedelta(days=1)
        self.pack = self.make_pack(
            10, granted_at=self.grant_time, expires_at=self.expiry_time
        )
        with patch(
            "apps.bookings.services.timezone.now", return_value=self.booking_time
        ):
            body, _ = book_class(self.member, self.session.pk, "historical")
        with patch(
            "apps.bookings.services.timezone.now", return_value=self.refund_time
        ):
            cancel_booking(self.member, body["id"])
        # Backfilled events must be selected by effective time, not insertion time.
        self.pack.movements.update(recorded_at=self.now)
        self.client.force_authenticate(self.member)

    def balance(self, at: datetime, **params: str | int) -> Response:
        return self.client.get(
            reverse("credit_balance"), {"at": at.isoformat(), **params}
        )

    def test_grant_charge_refund_and_expiry_boundaries(self) -> None:
        epsilon = timedelta(microseconds=1)
        cases = [
            (self.grant_time - epsilon, None),
            (self.grant_time, 10),
            (self.booking_time - epsilon, 10),
            (self.booking_time, 7),
            (self.refund_time - epsilon, 7),
            (self.refund_time, 10),
            (self.expiry_time - epsilon, 10),
            (self.expiry_time, None),
            (self.now, None),
        ]
        for at, expected in cases:
            with self.subTest(at=at):
                response = self.balance(at)
                self.assertEqual(response.status_code, 200)
                if expected is None:
                    self.assertEqual(response.data, {"studios": []})
                else:
                    studio = response.data["studios"][0]
                    self.assertEqual(studio["id"], self.studio.pk)
                    self.assertEqual(studio["total_credits"], expected)
                    self.assertEqual(
                        studio["credit_packs"][0]["credits_remaining"], expected
                    )

    def test_groups_only_owned_packs_valid_at_the_requested_time(self) -> None:
        at = self.now - timedelta(days=2)
        self.make_pack(2, granted_at=self.now - timedelta(days=4))
        self.make_pack(80, granted_at=self.now - timedelta(days=1))
        self.make_pack(
            90,
            granted_at=self.grant_time,
            expires_at=self.now - timedelta(days=3),
        )
        self.make_pack(100, member=self.other_member, granted_at=self.grant_time)
        other_studio = Studio.objects.create(name="Historical Pilates")
        self.make_pack(5, studio=other_studio, granted_at=self.grant_time)

        with self.assertNumQueries(2):
            response = self.balance(at, member=self.other_member.pk)

        self.assertEqual(response.status_code, 200)
        studios = {row["id"]: row for row in response.data["studios"]}
        self.assertEqual(studios[self.studio.pk]["total_credits"], 12)
        self.assertEqual(studios[other_studio.pk]["total_credits"], 5)
        self.assertEqual(len(studios[self.studio.pk]["credit_packs"]), 2)
        for row in studios.values():
            self.assertEqual(
                row["total_credits"],
                sum(pack["credits_remaining"] for pack in row["credit_packs"]),
            )

    def test_equivalent_timezone_offsets_return_the_same_snapshot(self) -> None:
        india = datetime_timezone(timedelta(hours=5, minutes=30))
        self.assertEqual(
            self.balance(self.booking_time).data,
            self.balance(self.booking_time.astimezone(india)).data,
        )

    def test_invalid_empty_and_future_timestamps_return_400(self) -> None:
        for at in ["invalid", "", (self.now + timedelta(days=1)).isoformat()]:
            with self.subTest(at=at):
                response = self.client.get(reverse("credit_balance"), {"at": at})
                self.assertEqual(response.status_code, 400)
                self.assertIn("at", response.data)

    def test_historical_balance_requires_authentication(self) -> None:
        self.client.force_authenticate(None)
        self.assertEqual(self.balance(self.booking_time).status_code, 401)

    def test_empty_member_history_returns_empty_list(self) -> None:
        self.client.force_authenticate(self.other_member)
        self.assertEqual(self.balance(self.booking_time).data, {"studios": []})

    def test_no_timestamp_preserves_current_balance_behavior(self) -> None:
        response = self.client.get(reverse("credit_balance"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"studios": []})
        self.assertEqual(
            self.balance(self.booking_time).data["studios"][0]["total_credits"], 7
        )
        self.pack.refresh_from_db()
        self.assertEqual(self.pack.credits_remaining, 10)


class CreditMovementAPITests(DomainFixtures, APITestCase):
    def test_registered_route_requires_authentication(self) -> None:
        url = reverse("credit_movements")
        self.assertEqual(url, "/studio/credit/movements")
        self.assertEqual(self.client.get(url).status_code, 401)

    def test_empty_history_returns_empty_list(self) -> None:
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse("credit_movements"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_history_preserves_causes_and_expired_packs_without_exposing_others(
        self,
    ) -> None:
        pack = self.make_pack(10)
        grant = pack.movements.get()
        with patch(
            "apps.bookings.services.timezone.now",
            return_value=self.now - timedelta(hours=3),
        ):
            body, _ = book_class(self.member, self.session.pk, "history")
        with patch(
            "apps.bookings.services.timezone.now",
            return_value=self.now - timedelta(hours=2),
        ):
            cancel_booking(self.member, body["id"])
        charge = pack.movements.get(kind="booking")
        refund = pack.movements.get(kind="refund")
        pack.expires_at = self.now - timedelta(hours=1)
        pack.save(update_fields=["expires_at"])
        other_studio = Studio.objects.create(name="Other studio")
        other_pack = self.make_pack(4, studio=other_studio)
        other_grant = other_pack.movements.get()
        self.make_pack(100, member=self.other_member)
        self.client.force_authenticate(self.member)

        with self.assertNumQueries(1):
            response = self.client.get(
                reverse("credit_movements"), {"member": self.other_member.pk}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.data],
            [grant.pk, other_grant.pk, charge.pk, refund.pk, None],
        )
        self.assertEqual(
            [(row["kind"], row["amount"]) for row in response.data],
            [
                ("grant", 10), ("grant", 4), ("booking", -3),
                ("refund", 3), ("expiry", -10),
            ],
        )
        for row in response.data:
            self.assertIsNotNone(row["effective_at"])
            if row["kind"] == "expiry":
                self.assertIsNone(row["id"])
                self.assertIsNone(row["recorded_at"])
            else:
                self.assertIsNotNone(row["recorded_at"])
            if row["id"] == other_grant.pk:
                self.assertEqual(row["pack_id"], other_pack.pk)
                self.assertEqual(row["studio"]["id"], other_studio.pk)
            else:
                self.assertEqual(row["pack_id"], pack.pk)
                self.assertEqual(row["studio"]["id"], self.studio.pk)
            if row["kind"] in ["grant", "expiry"]:
                self.assertIsNone(row["booking_id"])
            else:
                self.assertEqual(row["booking_id"], body["id"])


class GrantTransactionTests(DomainFixtures, TestCase):
    def test_movement_failure_rolls_back_pack(self) -> None:
        with (
            patch(
                "apps.studios.services.CreditMovement.objects.create",
                side_effect=IntegrityError("simulated ledger failure"),
            ),
            self.assertRaises(IntegrityError),
        ):
            grant_credit_pack(
                self.staff,
                self.studio,
                {
                    "member": self.member,
                    "credits_remaining": 10,
                    "expires_at": self.now + timedelta(days=30),
                },
            )
        self.assertFalse(CreditPack.objects.exists())
        self.assertFalse(CreditMovement.objects.exists())

    def test_original_grant_remains_valid_after_spending(self) -> None:
        pack = self.make_pack(10)
        original_grant = pack.movements.get(kind="grant")
        book_class(self.member, self.session.pk, "spend-before-validation")
        original_grant.refresh_from_db()
        # The original grant stays +10 even though the current balance is now 7.
        original_grant.full_clean()
