"""Load debug fixtures before the development server starts serving requests."""

from typing import Any

from django.contrib.staticfiles.management.commands.runserver import (
    Command as Runserver,
)
from django.core.handlers.wsgi import WSGIHandler

from apps.bookings.fixtures import seed_demo_data


class Command(Runserver):
    """Preserve Django's runserver behavior and seed debug data after checks."""

    def get_handler(self, *args: Any, **options: Any) -> WSGIHandler:
        """Seed in the serving process, including on autoreloader restarts."""
        if seed_demo_data():
            self.stdout.write(
                "Loaded debug demo fixtures; see README for login details."
            )
        return super().get_handler(*args, **options)
