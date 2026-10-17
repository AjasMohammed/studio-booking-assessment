"""Fast, isolated test configuration; never use these settings to serve requests."""

from .settings import *  # noqa: F403

SECRET_KEY = "test-only-signing-key-not-for-deployment-0123456789abcdef"  # noqa: S105
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Keep the test database distinct from both application data and Django's default.
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":  # noqa: F405
    DATABASES["default"]["TEST"] = {"NAME": "test_studio_edge_cases"}  # noqa: F405
