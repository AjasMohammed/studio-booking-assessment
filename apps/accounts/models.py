from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    STAFF = "staff", "Staff"
    MEMBER = "member", "Member"


class User(AbstractUser):
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
