from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework import serializers

UserModel = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    id = serializers.PrimaryKeyRelatedField(read_only=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = UserModel
        fields = (
            "id",
            "username",
            "email",
            "password",
            "role"
        )

    def validate(self, attrs):
        user = UserModel(
            username=attrs["username"],
            email=attrs["email"]
        )
        try:
            validate_password(attrs['password'], user)
        except ValidationError as exc:
            raise serializers.ValidationError(
                {'password': exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        return UserModel.objects.create_user(**validated_data)
