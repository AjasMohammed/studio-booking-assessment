from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.bookings.models import (
    Booking,
    BookingStatus,
    EntryStatus,
    IdempotencyRecord,
    WaitlistEntry,
)
from apps.studios.models import ClassSessions, CreditMovement, CreditPack, Studio


class ModelIntegrityTests(TestCase):
    def setUp(self) -> None:
        self.now = timezone.now()
        self.staff = User.objects.create(username="staff", role=Role.STAFF)
        self.member = User.objects.create(username="member")
        self.other_member = User.objects.create(username="other")
        self.studio = Studio.objects.create(name="Yoga", timezone="Asia/Kolkata")
        self.session = ClassSessions.objects.create(
            studio=self.studio,
            starts_at=self.now + timedelta(days=2),
            duration_minutes=60,
            capacity=2,
            credit_cost=3,
        )
        self.pack = CreditPack.objects.create(
            member=self.member,
            studio=self.studio,
            credits_remaining=10,
            granted_by=self.staff,
            granted_at=self.now,
            expires_at=self.now + timedelta(days=30),
        )
        self.booking = Booking.objects.create(
            member=self.member,
            class_session=self.session,
            credits_charged=3,
            cancellation_deadline=self.session.starts_at - timedelta(hours=4),
        )

    def test_class_accepts_short_duration_and_free_cost(self) -> None:
        self.session.duration_minutes = 10
        self.session.credit_cost = 0
        self.session.full_clean()

    def test_class_validation_rejects_zero_duration(self) -> None:
        self.session.duration_minutes = 0
        with self.assertRaises(ValidationError):
            self.session.full_clean()

    def test_studio_validates_timezone_and_accepts_zero_cutoff(self) -> None:
        self.studio.cancellation_cutoff_hours = 0
        self.studio.full_clean()
        self.studio.timezone = "Not/A_Timezone"
        with self.assertRaises(ValidationError):
            self.studio.full_clean()

    def test_database_rejects_invalid_class_values(self) -> None:
        for field, value in [
            ("duration_minutes", -1),
            ("capacity", -1),
            ("credit_cost", -1),
        ]:
            with (
                self.subTest(field=field),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                ClassSessions.objects.filter(pk=self.session.pk).update(
                    **{field: value}
                )

    def test_database_rejects_zero_duration_and_capacity(self) -> None:
        for field in ["duration_minutes", "capacity"]:
            with (
                self.subTest(field=field),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                ClassSessions.objects.filter(pk=self.session.pk).update(**{field: 0})

    def test_pack_requires_nonnegative_grant_and_expiry_after_grant(self) -> None:
        for values in [{"credits_remaining": -1}, {"expires_at": self.pack.granted_at}]:
            with (
                self.subTest(values=values),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                CreditPack.objects.filter(pk=self.pack.pk).update(**values)

    def test_pack_validates_member_and_staff_roles(self) -> None:
        self.pack.member = self.staff
        self.pack.granted_by = self.member
        with self.assertRaises(ValidationError):
            self.pack.full_clean()

    def test_duplicate_confirmed_booking_is_rejected(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(
                member=self.member,
                class_session=self.session,
                credits_charged=3,
                cancellation_deadline=self.booking.cancellation_deadline,
            )

    def test_cancelled_booking_preserved_when_member_books_again(self) -> None:
        self.booking.status = BookingStatus.CANCELLED
        self.booking.cancelled_at = self.now
        self.booking.save()
        Booking.objects.create(
            member=self.member,
            class_session=self.session,
            credits_charged=3,
            cancellation_deadline=self.booking.cancellation_deadline,
        )
        self.assertEqual(Booking.objects.filter(member=self.member).count(), 2)

    def test_cancelled_booking_requires_cancellation_time(self) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.filter(pk=self.booking.pk).update(status="cancelled")

    def test_one_charge_and_one_refund_per_pack_booking(self) -> None:
        for kind, amount in [
            ("booking", -3),
            ("refund", 3),
        ]:
            CreditMovement.objects.create(
                pack=self.pack, booking=self.booking, kind=kind, amount=amount
            )
            with self.assertRaises(IntegrityError), transaction.atomic():
                CreditMovement.objects.create(
                    pack=self.pack, booking=self.booking, kind=kind, amount=amount
                )

    def test_grant_cannot_be_recorded_twice(self) -> None:
        CreditMovement.objects.create(pack=self.pack, kind="grant", amount=10)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CreditMovement.objects.create(pack=self.pack, kind="grant", amount=10)

    def test_movement_rejects_invalid_sign_or_missing_cause(self) -> None:
        for kind, amount in [("grant", -10), ("booking", -3), ("refund", 3)]:
            with (
                self.subTest(kind=kind),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                CreditMovement.objects.create(pack=self.pack, kind=kind, amount=amount)

    def test_movement_validates_grant_amount_and_booking_owner(self) -> None:
        movement = CreditMovement(pack=self.pack, kind="grant", amount=9)
        with self.assertRaises(ValidationError):
            movement.full_clean()
        self.booking.member = self.other_member
        self.booking.save()
        movement = CreditMovement(
            pack=self.pack, booking=self.booking, kind="booking", amount=-3
        )
        with self.assertRaises(ValidationError):
            movement.full_clean()

    def test_movement_rejects_pack_from_another_studio(self) -> None:
        self.pack.studio = Studio.objects.create(name="Pilates")
        self.pack.save()
        movement = CreditMovement(
            pack=self.pack, booking=self.booking, kind="booking", amount=-3
        )
        with self.assertRaises(ValidationError):
            movement.full_clean()

    def test_waitlist_rejoin_preserves_previous_entry(self) -> None:
        entry = WaitlistEntry.objects.create(
            member=self.other_member, class_session=self.session
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            WaitlistEntry.objects.create(
                member=self.other_member, class_session=self.session
            )
        entry.status = EntryStatus.WITHDRAWN
        entry.withdrawn_at = self.now
        entry.save()
        WaitlistEntry.objects.create(
            member=self.other_member, class_session=self.session
        )
        self.assertEqual(WaitlistEntry.objects.count(), 2)

    def test_promotion_requires_matching_booking(self) -> None:
        entry = WaitlistEntry(
            member=self.other_member,
            class_session=self.session,
            status=EntryStatus.PROMOTED,
            booking=self.booking,
            promoted_at=self.now,
        )
        with self.assertRaises(ValidationError):
            entry.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            WaitlistEntry.objects.create(
                member=self.other_member,
                class_session=self.session,
                status=EntryStatus.PROMOTED,
            )

    def test_idempotency_key_scoped_to_member(self) -> None:
        IdempotencyRecord.objects.create(
            member=self.member,
            key="request-1",
            request_fingerprint="a" * 64,
            booking=self.booking,
            response_body={"booking_id": self.booking.pk},
        )
        other_booking = Booking.objects.create(
            member=self.other_member,
            class_session=self.session,
            credits_charged=3,
            cancellation_deadline=self.booking.cancellation_deadline,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            IdempotencyRecord.objects.create(
                member=self.member,
                key="request-1",
                request_fingerprint="b" * 64,
                booking=other_booking,
            )
        IdempotencyRecord.objects.create(
            member=self.other_member,
            key="request-1",
            request_fingerprint="b" * 64,
            booking=other_booking,
        )

    def test_idempotency_validates_booking_owner(self) -> None:
        record = IdempotencyRecord(
            member=self.other_member,
            key="request-1",
            request_fingerprint="a" * 64,
            booking=self.booking,
            response_body={"booking_id": self.booking.pk},
        )
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_accounting_relationships_protect_history_from_deletion(self) -> None:
        CreditMovement.objects.create(pack=self.pack, kind="grant", amount=10)
        for instance in [self.pack, self.studio, self.member, self.staff]:
            with (
                self.subTest(model=type(instance).__name__),
                self.assertRaises(ProtectedError),
            ):
                instance.delete()
