from datetime import UTC, timedelta
from datetime import timezone as datetime_timezone
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.bookings.services import book_class
from apps.studios.models import ClassSessions, CreditMovement, CreditPack, Studio
from apps.studios.services import grant_credit_pack
from apps.testing import DomainFixtures


class StudioAPITests(DomainFixtures, APITestCase):
    def test_studio_creation_requires_staff(self):
        url = reverse("create_studio")
        self.assertEqual(self.client.post(url, {"name": "New"}).status_code, 401)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(url, {"name": "New"}).status_code, 403)
        self.client.force_authenticate(self.staff)
        response = self.client.post(url, {"name": "New"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(Studio.objects.filter(pk=response.data["studio_id"]).exists())

    def test_studio_rejects_bad_timezone_negative_cutoff_and_duplicate_name(self):
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

    def test_zero_cancellation_cutoff_is_allowed(self):
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

    def class_payload(self, **overrides):
        data = {
            "starts_at": (self.now + timedelta(days=1)).isoformat(),
            "duration_minutes": 60,
            "capacity": 10,
            "credit_cost": 3,
        }
        data.update(overrides)
        return data

    def test_class_creation_links_url_studio_and_rejects_member(self):
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

    def test_class_creation_unknown_studio_is_404(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.post(
                reverse("create_class_session", args=[999999]),
                self.class_payload(),
                format="json",
            ).status_code,
            404,
        )

    def test_class_rejects_past_exact_now_and_malformed_start(self):
        self.client.force_authenticate(self.staff)
        for start in [
            self.now.isoformat(),
            (self.now - timedelta(seconds=1)).isoformat(),
            "not-a-date",
        ]:
            with (
                self.subTest(start=start),
                patch("apps.studios.services.timezone.now", return_value=self.now),
            ):
                self.assertEqual(
                    self.client.post(
                        reverse("create_class_session", args=[self.studio.pk]),
                        self.class_payload(starts_at=start),
                        format="json",
                    ).status_code,
                    400,
                )

    def test_class_rejects_nonpositive_duration_capacity_and_negative_cost(self):
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

    def test_equivalent_offsets_save_same_start_instant(self):
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


class CreditAPITests(DomainFixtures, APITestCase):
    def grant_payload(self, **overrides):
        data = {
            "member": self.member.pk,
            "credits_remaining": 10,
            "expires_at": (self.now + timedelta(days=30)).isoformat(),
        }
        data.update(overrides)
        return data

    def grant(self, **overrides):
        return self.client.post(
            reverse("grant_credit_pack", args=[self.studio.pk]),
            self.grant_payload(**overrides),
            format="json",
        )

    def test_grant_requires_staff(self):
        self.assertEqual(self.grant().status_code, 401)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.grant().status_code, 403)
        self.assertFalse(CreditPack.objects.exists())

    def test_valid_grant_records_staff_amount_and_same_effective_time(self):
        self.client.force_authenticate(self.staff)
        response = self.grant()
        self.assertEqual(response.status_code, 201)
        pack = CreditPack.objects.get(pk=response.data["id"])
        movement = pack.movements.get()
        self.assertEqual(pack.granted_by_id, self.staff.pk)
        self.assertEqual(pack.studio_id, self.studio.pk)
        self.assertEqual(movement.amount, pack.credits_remaining)
        self.assertEqual(movement.effective_at, pack.granted_at)

    def test_each_grant_preserves_separate_pack_and_expiry(self):
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

    def test_grant_cannot_override_staff_or_url_studio(self):
        other_studio = Studio.objects.create(name="Other studio")
        self.client.force_authenticate(self.staff)
        response = self.grant(studio=other_studio.pk, granted_by=self.member.pk)
        self.assertEqual(response.status_code, 201)
        pack = CreditPack.objects.get(pk=response.data["id"])
        self.assertEqual(pack.studio_id, self.studio.pk)
        self.assertEqual(pack.granted_by_id, self.staff.pk)

    def test_grant_rejects_zero_negative_fractional_and_invalid_recipient(self):
        self.client.force_authenticate(self.staff)
        for data in [
            {"credits_remaining": 0},
            {"credits_remaining": -1},
            {"credits_remaining": 1.5},
            {"member": self.staff.pk},
            {"member": 999999},
        ]:
            with self.subTest(data=data):
                self.assertEqual(self.grant(**data).status_code, 400)
        self.assertFalse(CreditPack.objects.exists())
        self.assertFalse(CreditMovement.objects.exists())

    def test_grant_rejects_expiry_at_or_before_now(self):
        self.client.force_authenticate(self.staff)
        for expiry in [self.now, self.now - timedelta(seconds=1)]:
            with (
                self.subTest(expiry=expiry),
                patch("apps.studios.services.timezone.now", return_value=self.now),
            ):
                self.assertEqual(
                    self.grant(expires_at=expiry.isoformat()).status_code, 400
                )

    def test_oversized_grant_returns_validation_error_not_server_error(self):
        self.client.force_authenticate(self.staff)
        self.client.raise_request_exception = False
        self.assertEqual(self.grant(credits_remaining=2**63).status_code, 400)
        self.assertFalse(CreditPack.objects.exists())

    def test_grant_unknown_studio_is_404(self):
        self.client.force_authenticate(self.staff)
        self.assertEqual(
            self.client.post(
                reverse("grant_credit_pack", args=[999999]),
                self.grant_payload(),
                format="json",
            ).status_code,
            404,
        )

    def test_balance_groups_packs_and_excludes_others_expired_and_future(self):
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

    def test_balance_respects_exact_grant_and_expiry_boundaries(self):
        self.make_pack(3, granted_at=self.now)
        self.make_pack(50, expires_at=self.now)
        self.client.force_authenticate(self.member)
        with patch("apps.studios.views.credits.timezone.now", return_value=self.now):
            response = self.client.get(reverse("credit_balance"))
        self.assertEqual(response.data["studios"][0]["total_credits"], 3)

    def test_balance_requires_auth_and_empty_account_returns_empty_list(self):
        self.assertEqual(self.client.get(reverse("credit_balance")).status_code, 401)
        self.client.force_authenticate(self.member)
        self.assertEqual(
            self.client.get(reverse("credit_balance")).data, {"studios": []}
        )

    def test_balance_uses_authenticated_member_not_query_parameter(self):
        self.make_pack(80, member=self.other_member)
        self.client.force_authenticate(self.member)
        response = self.client.get(
            reverse("credit_balance"),
            {
                "member": self.other_member.pk,
            },
        )
        self.assertEqual(response.data, {"studios": []})

    def test_balance_reflects_booking_deductions(self):
        self.make_pack(10)
        book_class(self.member, self.session.pk, "book-for-balance")
        self.client.force_authenticate(self.member)
        response = self.client.get(reverse("credit_balance"))
        self.assertEqual(response.data["studios"][0]["total_credits"], 7)


class GrantTransactionTests(DomainFixtures, TestCase):
    def test_movement_failure_rolls_back_pack(self):
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

    def test_original_grant_remains_valid_after_spending(self):
        pack = self.make_pack(10)
        original_grant = pack.movements.get(kind="grant")
        book_class(self.member, self.session.pk, "spend-before-validation")
        original_grant.refresh_from_db()
        # The original grant stays +10 even though the current balance is now 7.
        original_grant.full_clean()
