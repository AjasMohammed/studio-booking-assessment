from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    """Application roles used for staff and member access checks."""
    STAFF = "staff", "Staff"
    MEMBER = "member", "Member"


class User(AbstractUser):
    """Django user with an application role separate from admin-site permissions."""
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
