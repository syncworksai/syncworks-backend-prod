from django.urls import path

from user_accounts.views.registration import (
    ResendEmailCodeAPIView,
    ResolveSignupCodesAPIView,
    StartEmailVerificationAPIView,
    VerifiedRegisterAPIView,
    VerifyEmailCodeAPIView,
)

urlpatterns = [
    path(
        "email/start-verification/",
        StartEmailVerificationAPIView.as_view(),
        name="auth-email-start-verification",
    ),
    path(
        "email/verify-code/",
        VerifyEmailCodeAPIView.as_view(),
        name="auth-email-verify-code",
    ),
    path(
        "email/resend-code/",
        ResendEmailCodeAPIView.as_view(),
        name="auth-email-resend-code",
    ),
    path(
        "resolve-signup-codes/",
        ResolveSignupCodesAPIView.as_view(),
        name="auth-resolve-signup-codes",
    ),
    path(
        "register/",
        VerifiedRegisterAPIView.as_view(),
        name="auth-verified-register",
    ),
]