"""Shared fixtures for domain tests; helpers do not call the services under test."""

from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import Role, User
from apps.studios.models import (
    ClassSessions,
    CreditKind,
    CreditMovement,
    CreditPack,
    Studio,
)


class DomainFixtures:
    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now().replace(microsecond=0)
        self.staff = User.objects.create_user(username="staff", role=Role.STAFF)
        self.member = User.objects.create_user(username="member")
        self.other_member = User.objects.create_user(username="other-member")
        self.studio = Studio.objects.create(name="Yoga", timezone="Asia/Kolkata")
        self.session = self.make_session()

    def make_session(self, **overrides):
        values = {
            "studio": self.studio,
            "starts_at": self.now + timedelta(days=2),
            "duration_minutes": 60,
            "capacity": 2,
            "credit_cost": 3,
        }
        values.update(overrides)
        return ClassSessions.objects.create(**values)

    def make_pack(self, credits=10, **overrides):
        values = {
            "member": self.member,
            "studio": self.studio,
            "granted_by": self.staff,
            "credits_remaining": credits,
            "granted_at": self.now - timedelta(days=1),
            "expires_at": self.now + timedelta(days=30),
        }
        values.update(overrides)
        pack = CreditPack.objects.create(**values)
        if credits:
            CreditMovement.objects.create(
                pack=pack,
                kind=CreditKind.GRANT,
                amount=credits,
                effective_at=pack.granted_at,
            )
        return pack
