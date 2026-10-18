"""Real competing transactions; skipped on SQLite, which has no row locks."""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue
from threading import Event
from time import monotonic, sleep
from unittest import skipUnless
from unittest.mock import patch

from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase
from rest_framework.exceptions import APIException

from apps.accounts.models import User
from apps.bookings.models import Booking, IdempotencyRecord
from apps.bookings.services import book_class
from apps.studios.models import ClassSessions, CreditMovement, CreditPack
from apps.testing import DomainFixtures
from apps.testing_types import RaceResult


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locking.")
class BookingConcurrencyTests(DomainFixtures, TransactionTestCase):
    def race(
        self, calls: Sequence[tuple[int, int, str]], *,
        lock_classes: Sequence[int] = (), lock_packs: Sequence[int] = (),
        after_wait: Callable[[], None] | None = None,
    ) -> list[RaceResult]:
        """Queue workers behind real locks, then release them together.

        No barrier is inserted inside the service's critical section: a correct
        member lock must be able to serialize requests before their key lookup.
        """
        pids: Queue[int] = Queue()
        start = Event()

        def worker(member_id: int, class_id: int, key: str) -> RaceResult:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '12s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    pids.put(cursor.fetchone()[0])
                if not start.wait(timeout=8):
                    raise TimeoutError("Test workers did not start.")
                member = User.objects.get(pk=member_id)
                body, status = book_class(member, class_id, key)
                return {"status": status, "body": body}
            except APIException as exc:
                return {"status": exc.status_code, "error": str(exc)}
            except Exception as exc:
                return {"status": 500, "error": f"{type(exc).__name__}: {exc}"}
            finally:
                connections["default"].close()

        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            with transaction.atomic():
                list(
                    ClassSessions.objects.select_for_update()
                    .filter(pk__in=lock_classes)
                    .order_by("pk")
                )
                list(
                    CreditPack.objects.select_for_update()
                    .filter(pk__in=lock_packs)
                    .order_by("pk")
                )
                futures = [executor.submit(worker, *call) for call in calls]
                try:
                    worker_pids = [pids.get(timeout=8) for _ in calls]
                    start.set()
                    deadline = monotonic() + 4
                    waiting = 0
                    while monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT pg_stat_clear_snapshot()")
                            cursor.execute(
                                "SELECT COUNT(*) FROM pg_stat_activity "
                                "WHERE pid = ANY(%s) AND wait_event_type = 'Lock'",
                                [worker_pids],
                            )
                            waiting = cursor.fetchone()[0]
                        if waiting == len(calls):
                            break
                        sleep(0.01)
                    self.assertEqual(
                        waiting,
                        len(calls),
                        "Workers did not reach the expected database lock waits.",
                    )
                    if after_wait is not None:
                        after_wait()
                finally:
                    start.set()
            return [future.result(timeout=15) for future in futures]

    def test_two_members_competing_for_last_seat_confirm_only_one(self) -> None:
        self.make_pack()
        self.make_pack(member=self.other_member)
        self.session.capacity = 1
        self.session.save()
        results = self.race(
            [
                (self.member.pk, self.session.pk, "first"),
                (self.other_member.pk, self.session.pk, "second"),
            ],
            lock_classes=[self.session.pk],
        )
        self.assertEqual(sorted(r["status"] for r in results), [201, 400], results)
        self.assertEqual(Booking.objects.filter(status="confirmed").count(), 1)
        self.assertEqual(CreditMovement.objects.filter(kind="booking").count(), 1)

    def test_simultaneous_identical_retries_replay_one_success(self) -> None:
        pack = self.make_pack()
        self.session.capacity = 1
        self.session.save()
        call = (self.member.pk, self.session.pk, "same-key")
        results = self.race([call, call], lock_classes=[self.session.pk])
        self.assertEqual([r["status"] for r in results], [201, 201], results)
        self.assertEqual(results[0]["body"], results[1]["body"])
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 7)

    def test_same_key_for_different_classes_returns_conflict_not_server_error(
        self,
    ) -> None:
        self.make_pack()
        other_session = self.make_session()
        results = self.race(
            [
                (self.member.pk, self.session.pk, "same-key"),
                (self.member.pk, other_session.pk, "same-key"),
            ],
            lock_classes=[self.session.pk, other_session.pk],
        )
        self.assertEqual(sorted(r["status"] for r in results), [201, 409], results)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_different_classes_cannot_overspend_shared_account(self) -> None:
        pack = self.make_pack(5)
        other_session = self.make_session()
        results = self.race(
            [
                (self.member.pk, self.session.pk, "class-one"),
                (self.member.pk, other_session.pk, "class-two"),
            ],
            lock_classes=[self.session.pk, other_session.pk],
        )
        self.assertEqual(sorted(r["status"] for r in results), [201, 400], results)
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 2)
        self.assertEqual(Booking.objects.count(), 1)

    def test_different_keys_and_classes_can_both_spend_when_balance_suffices(
        self,
    ) -> None:
        pack = self.make_pack(6)
        other_session = self.make_session()
        results = self.race(
            [
                (self.member.pk, self.session.pk, "class-one"),
                (self.member.pk, other_session.pk, "class-two"),
            ],
            lock_classes=[self.session.pk, other_session.pk],
        )
        self.assertEqual([r["status"] for r in results], [201, 201], results)
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 0)
        self.assertEqual(Booking.objects.count(), 2)

    def test_class_starting_during_lock_wait_is_rejected(self) -> None:
        self.make_pack()
        clock = [self.now]

        def advance_clock() -> None:
            clock[0] = self.session.starts_at

        with patch("apps.bookings.services.timezone.now", side_effect=lambda: clock[0]):
            results = self.race(
                [
                    (self.member.pk, self.session.pk, "waiting-class"),
                ],
                lock_classes=[self.session.pk],
                after_wait=advance_clock,
            )
        self.assertEqual(results[0]["status"], 400, results)
        self.assertFalse(Booking.objects.exists())

    def test_pack_expiring_during_pack_lock_wait_is_not_spent(self) -> None:
        pack = self.make_pack(3, expires_at=self.now + timedelta(hours=1))
        clock = [self.now]

        def advance_clock() -> None:
            clock[0] = pack.expires_at

        with patch("apps.bookings.services.timezone.now", side_effect=lambda: clock[0]):
            results = self.race(
                [
                    (self.member.pk, self.session.pk, "waiting-pack"),
                ],
                lock_packs=[pack.pk],
                after_wait=advance_clock,
            )
        self.assertEqual(results[0]["status"], 400, results)
        self.assertFalse(Booking.objects.exists())
        pack.refresh_from_db()
        self.assertEqual(pack.credits_remaining, 3)

    def test_pack_expiring_during_wait_is_skipped_if_another_pack_can_pay(self) -> None:
        expiring = self.make_pack(3, expires_at=self.now + timedelta(hours=1))
        valid = self.make_pack(3)
        clock = [self.now]

        def advance_clock() -> None:
            clock[0] = expiring.expires_at

        with patch("apps.bookings.services.timezone.now", side_effect=lambda: clock[0]):
            results = self.race(
                [
                    (self.member.pk, self.session.pk, "skip-expired"),
                ],
                lock_packs=[expiring.pk],
                after_wait=advance_clock,
            )
        self.assertEqual(results[0]["status"], 201, results)
        expiring.refresh_from_db()
        valid.refresh_from_db()
        self.assertEqual((expiring.credits_remaining, valid.credits_remaining), (3, 0))

    def test_future_pack_becoming_usable_during_wait_can_fund_booking(self) -> None:
        first = self.make_pack(1)
        future = self.make_pack(
            3,
            granted_at=self.now + timedelta(hours=1),
            expires_at=self.now + timedelta(days=40),
        )
        clock = [self.now]

        def advance_clock() -> None:
            clock[0] = future.granted_at

        with patch("apps.bookings.services.timezone.now", side_effect=lambda: clock[0]):
            results = self.race(
                [
                    (self.member.pk, self.session.pk, "grant-becomes-valid"),
                ],
                lock_packs=[first.pk],
                after_wait=advance_clock,
            )
        self.assertEqual(results[0]["status"], 201, results)
        first.refresh_from_db()
        future.refresh_from_db()
        self.assertEqual((first.credits_remaining, future.credits_remaining), (0, 1))
