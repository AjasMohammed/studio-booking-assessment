from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework import serializers

from apps.accounts.models import User

UserModel = get_user_model()


class UserSerializer(serializers.ModelSerializer[User]):
    """Serialize user details and validate passwords before account creation."""
    id = serializers.PrimaryKeyRelatedField[User](read_only=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, trim_whitespace=False)

    class Meta:
        """Declare serialized fields and their model mapping."""
        model = UserModel
        fields = ("id", "username", "email", "password", "role")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Apply Django password rules using the submitted user details."""
        user = UserModel(username=attrs["username"], email=attrs["email"])
        try:
            validate_password(attrs["password"], user)
        except ValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def create(self, validated_data: dict[str, Any]) -> User:
        """Create the user through Django's manager so the password is hashed."""
        return UserModel.objects.create_user(**validated_data)
