from rest_framework import serializers
from rest_framework.exceptions import APIException


class IdempotencyConflict(APIException):
    """Return HTTP 409 when a member reuses a key for a different request."""
    status_code = 409
    default_detail = "This idempotency key was already used for a different request."
    default_code = "idempotency_conflict"


class InsufficientCredits(serializers.ValidationError):
    """Reject a charge when usable packs cannot cover the class cost."""
    default_detail = "Insufficient credits!"


class NoSeatsAvailable(serializers.ValidationError):
    """Reject booking when confirmed reservations have reached capacity."""
    default_detail = "No seats are available!"


class ClassAlreadyStarted(serializers.ValidationError):
    """Reject joining or booking a class whose start time has passed."""
    default_detail = "Class already started!"
