"""Debug fixtures stay isolated, atomic, and safe to load on each server start."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.management import get_commands, load_command_class
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.bookings.fixtures import DEMO_PASSWORD, DEMO_STUDIO_NAME, seed_demo_data
from apps.bookings.management.commands.runserver import Command
from apps.bookings.models import Booking, EntryStatus, IdempotencyRecord, WaitlistEntry
from apps.bookings.services import cancel_booking
from apps.studios.models import ClassSessions, CreditMovement, CreditPack, Studio
from apps.studios.selectors import credit_balances
from apps.studios.serializers import StudioCreditBalanceSerializer
from apps.studios.services import credit_history


@override_settings(DEBUG=True)
class DemoFixtureTests(TestCase):
    def test_fixtures_have_usable_logins_and_consistent_accounting(self) -> None:
        self.assertTrue(seed_demo_data())
        self.assertEqual(User.objects.count(), 4)
        self.assertEqual(User.objects.get(username="demo-staff").role, Role.STAFF)
        for user in User.objects.all():
            self.assertTrue(user.check_password(DEMO_PASSWORD))
            self.assertFalse(user.is_staff)
            self.assertFalse(user.is_superuser)
        self.assertEqual(ClassSessions.objects.count(), 3)
        self.assertEqual(Booking.objects.count(), 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 2)
        for name in ["demo-alice", "demo-bob"]:
            member = User.objects.get(username=name)
            self.assertEqual(
                StudioCreditBalanceSerializer(credit_balances(member), many=True)
                .data[0]["total_credits"],
                7,
            )
        for pack in CreditPack.objects.all():
            self.assertEqual(
                sum(pack.movements.values_list("amount", flat=True)),
                pack.credits_remaining,
            )
        alice_booking = Booking.objects.get(member__username="demo-alice")
        self.assertEqual(
            list(
                alice_booking.credit_movements.order_by("pack__expires_at").values_list(
                    "amount", flat=True
                )
            ),
            [-2, -1],
        )
        charlie = User.objects.get(username="demo-charlie")
        self.assertFalse(credit_balances(charlie).exists())
        self.assertEqual(
            [(event["kind"], event["amount"]) for event in credit_history(charlie)],
            [("grant", 5), ("expiry", -5)],
        )

    def test_seeded_cancellation_skips_unaffordable_waiter_and_promotes_bob(
        self,
    ) -> None:
        seed_demo_data()
        alice_booking = Booking.objects.get(member__username="demo-alice")
        cancel_booking(alice_booking.member, alice_booking.pk)
        entries = WaitlistEntry.objects.order_by("joined_at", "pk")
        self.assertEqual(
            list(entries.values_list("member__username", "status")),
            [("demo-charlie", EntryStatus.WAITING), ("demo-bob", EntryStatus.PROMOTED)],
        )
        promoted = entries.get(status=EntryStatus.PROMOTED)
        assert promoted.booking_id is not None
        booking = Booking.objects.get(pk=promoted.booking_id)
        self.assertEqual(booking.member.username, "demo-bob")
        self.assertEqual(booking.class_session_id, alice_booking.class_session_id)

    def test_seeded_late_cancellation_forfeits_credits(self) -> None:
        seed_demo_data()
        booking = Booking.objects.get(member__username="demo-bob")
        self.assertLess(booking.cancellation_deadline, timezone.now())
        cancel_booking(booking.member, booking.pk)
        self.assertFalse(booking.credit_movements.filter(kind="refund").exists())
        self.assertEqual(
            CreditPack.objects.get(member=booking.member).credits_remaining, 7
        )

    def test_repeated_startup_preserves_passwords_data_and_changes(self) -> None:
        seed_demo_data()
        staff = User.objects.get(username="demo-staff")
        staff.set_password("ChangedOnly!Cedar-473")
        staff.save()
        booking = Booking.objects.get(member__username="demo-alice")
        cancel_booking(booking.member, booking.pk)
        movements = list(CreditMovement.objects.values_list("pk", "amount"))
        with patch(
            "apps.bookings.fixtures.timezone.now",
            return_value=timezone.now() + timedelta(days=60),
        ):
            self.assertFalse(seed_demo_data())
        staff.refresh_from_db()
        booking.refresh_from_db()
        self.assertTrue(staff.check_password("ChangedOnly!Cedar-473"))
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(User.objects.count(), 4)
        self.assertEqual(Studio.objects.count(), 1)
        self.assertEqual(ClassSessions.objects.count(), 3)
        self.assertEqual(
            list(CreditMovement.objects.values_list("pk", "amount")), movements
        )

    @override_settings(DEBUG=False)
    def test_debug_false_never_reads_or_writes_fixture_data(self) -> None:
        with self.assertNumQueries(0):
            self.assertFalse(seed_demo_data())

    def test_failed_seed_rolls_back_all_demo_data(self) -> None:
        with (
            patch(
                "apps.bookings.fixtures.join_waitlist",
                side_effect=RuntimeError("failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            seed_demo_data()
        for model in [
            User,
            Studio,
            ClassSessions,
            CreditPack,
            CreditMovement,
            Booking,
            WaitlistEntry,
            IdempotencyRecord,
        ]:
            self.assertFalse(model._default_manager.exists())
        self.assertTrue(seed_demo_data())

    def test_existing_account_is_never_overwritten_or_granted_staff_role(self) -> None:
        existing = User.objects.create_user(
            username="demo-staff", password="Existing!473"
        )
        with self.assertRaisesMessage(CommandError, "Demo usernames already exist"):
            seed_demo_data()
        existing.refresh_from_db()
        self.assertEqual(existing.role, Role.MEMBER)
        self.assertTrue(existing.check_password("Existing!473"))
        self.assertFalse(Studio.objects.filter(name=DEMO_STUDIO_NAME).exists())

    def test_runserver_discovers_override_and_keeps_static_file_handler(self) -> None:
        self.assertEqual(get_commands()["runserver"], "apps.bookings")
        command = load_command_class("apps.bookings", "runserver")
        assert isinstance(command, Command)
        command.stdout = command.stdout.__class__(StringIO())
        handler = command.get_handler(use_static_handler=True, insecure_serving=False)
        self.assertIsInstance(handler, StaticFilesHandler)
        self.assertEqual(User.objects.count(), 4)
        command.get_handler(use_static_handler=True, insecure_serving=False)
        self.assertEqual(User.objects.count(), 4)

    @override_settings(DEBUG=False)
    def test_runserver_with_debug_false_does_not_seed(self) -> None:
        command = load_command_class("apps.bookings", "runserver")
        assert isinstance(command, Command)
        with self.assertNumQueries(0):
            command.get_handler(use_static_handler=False, insecure_serving=False)
        self.assertFalse(User.objects.exists())
