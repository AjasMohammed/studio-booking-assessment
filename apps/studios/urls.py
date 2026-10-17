from django.urls import path

from apps.studios.views import (
    CreateSession,
    CreateStudio,
    CreditBalanceAPI,
    CreditMovementAPI,
    GrantCreditAPI,
    ListClassSessionsAPI,
    ListStudiosAPI,
)

urlpatterns = [
    path("create", CreateStudio.as_view(), name="create_studio"),
    path("list", ListStudiosAPI.as_view(), name="list_studios"),
    path("classes", ListClassSessionsAPI.as_view(), name="list_class_sessions"),
    path("<int:studio_id>/session/create",
         CreateSession.as_view(), name="create_class_session"),
    path("<int:studio_id>/credit/grant",
         GrantCreditAPI.as_view(), name="grant_credit_pack"),
    path("credit/balance",
         CreditBalanceAPI.as_view(), name="credit_balance"),
    path("credit/movements",
         CreditMovementAPI.as_view(), name="credit_movements"),
]
