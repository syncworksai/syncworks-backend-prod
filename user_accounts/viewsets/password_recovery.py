"""Account recovery with non-enumerating responses and one-use Django reset tokens."""
import hashlib

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

User = get_user_model()
GENERIC = "If an account uses this email, a password reset link will be sent."
LIMIT = 3


def _limited(key, limit=LIMIT, seconds=3600):
    # Cache-backed throttle. Production should use a shared cache across service workers.
    hashed = hashlib.sha256(key.encode("utf-8")).hexdigest()
    storage_key = "sw:password-reset:" + hashed
    if cache.add(storage_key, 1, timeout=seconds):
        return False
    try:
        return cache.incr(storage_key) > limit
    except (ValueError, AttributeError):
        cache.set(storage_key, limit + 1, timeout=seconds)
        return True


def _password_errors(password, user):
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        return exc.messages
    return []


class RequestPasswordResetAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        email = str(request.data.get("email") or "").strip().lower()[:254]
        if not email or "@" not in email:
            return Response({"detail": GENERIC})
        if _limited("email:" + email) or _limited("ip:" + str(request.META.get("REMOTE_ADDR") or "unknown"), limit=12):
            return Response({"detail": GENERIC})
        user = User.objects.filter(email__iexact=email, is_active=True).order_by("pk").first()
        if user and user.has_usable_password():
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            base = (getattr(settings, "FRONTEND_URL", "") or "https://syncworksapp.com").rstrip("/")
            url = f"{base}/reset-password?uid={uid}&token={token}"
            try:
                send_mail(
                    "Reset your SyncWorks password",
                    "We received a request to reset your SyncWorks password.\\n\\n"
                    f"Use this link to set a new password:\\n{url}\\n\\n"
                    "If you did not request this, you can ignore this email. "
                    "This link expires in one hour.",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email], fail_silently=False,
                )
            except Exception:
                # Do not reveal registration status or mail provider errors to unauthenticated callers.
                pass
        return Response({"detail": GENERIC})


class ConfirmPasswordResetAPIView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        uid = str(request.data.get("uid") or "")
        token = str(request.data.get("token") or "")
        password = request.data.get("new_password") or ""
        if len(uid) > 128 or len(token) > 256 or not isinstance(password, str):
            return Response({"detail": "Reset link is invalid or expired."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pk = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=pk, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist, UnicodeDecodeError):
            return Response({"detail": "Reset link is invalid or expired."}, status=status.HTTP_400_BAD_REQUEST)
        if not default_token_generator.check_token(user, token):
            return Response({"detail": "Reset link is invalid or expired."}, status=status.HTTP_400_BAD_REQUEST)
        errors = _password_errors(password, user)
        if errors:
            return Response({"new_password": errors}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user.set_password(password)
            user.save(update_fields=["password"])
            Token.objects.filter(user=user).delete()
        return Response({"detail": "Password updated. Please sign in again."})


class ChangePasswordAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current = request.data.get("current_password") or ""
        new = request.data.get("new_password") or ""
        user = request.user
        if not user.check_password(current):
            return Response({"current_password": ["Current password is incorrect."]}, status=status.HTTP_400_BAD_REQUEST)
        errors = _password_errors(new, user)
        if errors:
            return Response({"new_password": errors}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user.set_password(new)
            user.save(update_fields=["password"])
            Token.objects.filter(user=user).delete()
        return Response({"detail": "Password updated. Please sign in with your new password."})
