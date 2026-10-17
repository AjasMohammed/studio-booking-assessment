from django.apps import AppConfig


class BookingsConfig(AppConfig):
    """Register the bookings application with Django."""
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bookings"
