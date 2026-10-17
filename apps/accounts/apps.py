from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Register the accounts application with Django."""
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'
