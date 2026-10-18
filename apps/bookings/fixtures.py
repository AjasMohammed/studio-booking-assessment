"""Repeatable Python fixtures for exercising the API in debug mode."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.bookings.services import book_class, join_waitlist
from apps.studios.models import (
    ClassSessions,
    CreditKind,
    CreditMovement,
    CreditPack,
    Studio,
)
from apps.studios.services import grant_credit_pack

DEMO_PASSWORD = "DemoOnly!Cedar-473"  # noqa: S105  # Debug-only fixture credentials.
DEMO_STUDIO_NAME = "Demo Studio"


def seed_demo_data() -> bool:
    """Create demo data once, preserving all data and passwords on later starts."""
    if not settings.DEBUG:
        return False

    with transaction.atomic():
        studio, created = Studio.objects.get_or_create(
            name=DEMO_STUDIO_NAME,
            defaults={"timezone": "Asia/Kolkata", "cancellation_cutoff_hours": 4},
        )
        if not created:
            return False
        usernames = ("demo-staff", "demo-alice", "demo-bob", "demo-charlie")
        if User.objects.filter(username__in=usernames).exists():
            raise CommandError(
                "Demo usernames already exist without Demo Studio; "
                "rename the conflicting accounts before loading demo fixtures."
            )
        staff, alice, bob, charlie = [
            User.objects.create_user(
                username=username,
                email=f"{username}@example.com",
                password=DEMO_PASSWORD,
                role=Role.STAFF if username == "demo-staff" else Role.MEMBER,
            )
            for username in usernames
        ]
        now = timezone.now()
        for member, credits, days in [(alice, 2, 7), (alice, 8, 30), (bob, 10, 30)]:
            grant_credit_pack(
                staff,
                studio,
                {
                    "member": member,
                    "credits_remaining": credits,
                    "expires_at": now + timedelta(days=days),
                },
            )
        expired_pack = CreditPack.objects.create(
            member=charlie,
            studio=studio,
            granted_by=staff,
            credits_remaining=5,
            granted_at=now - timedelta(days=2),
            expires_at=now - timedelta(days=1),
        )
        CreditMovement.objects.create(
            pack=expired_pack,
            kind=CreditKind.GRANT,
            amount=5,
            effective_at=expired_pack.granted_at,
        )
        ClassSessions.objects.create(
            studio=studio,
            starts_at=now + timedelta(days=2),
            duration_minutes=60,
            capacity=3,
            credit_cost=3,
        )
        full_class = ClassSessions.objects.create(
            studio=studio,
            starts_at=now + timedelta(days=3),
            duration_minutes=60,
            capacity=1,
            credit_cost=3,
        )
        late_class = ClassSessions.objects.create(
            studio=studio,
            starts_at=now + timedelta(hours=2),
            duration_minutes=45,
            capacity=2,
            credit_cost=3,
        )
        book_class(alice, full_class.pk, "demo-alice-full")
        join_waitlist(charlie, full_class.pk)
        join_waitlist(bob, full_class.pk)
        book_class(bob, late_class.pk, "demo-bob-late")
    return True
