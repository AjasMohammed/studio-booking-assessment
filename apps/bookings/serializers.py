from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.studios.serializers import ClassSessionSerializer

from .models import WaitlistEntry


class WaitlistSerializer(serializers.ModelSerializer):
    """Represent a waitlist entry with nested member and class details."""
    class_session = ClassSessionSerializer()
    member = UserSerializer()

    class Meta:
        """Declare serialized fields and their model mapping."""
        model = WaitlistEntry
        fields = (
            "id",
            "member",
            "status",
            "class_session"
        )
