from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

from apps.accounts.views import SignUp

urlpatterns = [
    path("auth/signup", SignUp.as_view(), name="signup"),
    path("auth/login", TokenObtainPairView.as_view(), name="token_obtain_pair"),
        path("auth/refresh", TokenRefreshView.as_view(), name="token_refresh"),
]
