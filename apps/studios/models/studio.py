from zoneinfo import available_timezones

from django.core.validators import MinValueValidator
from django.db import models


def studio_timezone_choices() -> list[tuple[str, str]]:
    # A callable avoids freezing this machine's timezone database into migrations.
    return [(tz, tz) for tz in sorted(available_timezones() - {"localtime"})]


class Studio(models.Model):
    name = models.CharField(max_length=255, unique=True)
    timezone = models.CharField(
        max_length=64,
        choices=studio_timezone_choices,
        default="Asia/Kolkata",
    )
    cancellation_cutoff_hours = models.PositiveIntegerField(default=4)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class ClassSessions(models.Model):
    studio = models.ForeignKey(
        Studio,
        on_delete=models.PROTECT,
        related_name="class_sessions",
        null=False, blank=False
    )
    starts_at = models.DateTimeField(null=False)
    duration_minutes = models.PositiveIntegerField(
        default=20,
        validators=[MinValueValidator(1)]
    )
    capacity = models.PositiveIntegerField(default=1)
    credit_cost = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "pk"]
        indexes = [models.Index(fields=["studio", "starts_at"])]

    def __str__(self) -> str:
        return self.studio.name
