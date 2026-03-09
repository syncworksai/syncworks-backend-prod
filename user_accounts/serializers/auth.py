from django.contrib.auth import authenticate, get_user_model
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from user_accounts.models import CustomerProfile

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """
    Everyone registers as CUSTOMER.
    Upgrades happen later via /me/upgrade/* endpoints.
    """
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("id", "email", "username", "password", "first_name", "last_name")

    def validate(self, attrs):
        email = (attrs.get("email") or "").strip().lower()
        if not email:
            raise serializers.ValidationError({"email": "Email is required."})
        attrs["email"] = email
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")

        # FORCE role to CUSTOMER at signup
        user = User(**validated_data)
        user.role = "CUSTOMER"
        user.set_password(password)
        user.save()

        # baseline customer profile
        try:
            CustomerProfile.objects.get_or_create(user=user)
        except Exception:
            pass

        # create token on signup (front-end can auto-login)
        token, _ = Token.objects.get_or_create(user=user)

        return {"user": user, "token": token.key}


class TokenLoginSerializer(serializers.Serializer):
    """
    Accepts either email OR username in a single field.
    """
    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        identifier = (attrs.get("identifier") or "").strip()
        password = attrs.get("password") or ""

        if not identifier or not password:
            raise serializers.ValidationError("Missing credentials.")

        # Try username login first
        user = authenticate(username=identifier, password=password)

        # Fallback: email -> username
        if user is None:
            try:
                u = User.objects.filter(email__iexact=identifier).first()
                if u:
                    user = authenticate(username=u.username, password=password)
            except Exception:
                user = None

        if user is None:
            raise serializers.ValidationError("Invalid credentials.")

        token, _ = Token.objects.get_or_create(user=user)
        return {"token": token.key, "user_id": user.id}
