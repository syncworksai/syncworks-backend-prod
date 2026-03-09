from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from user_accounts.models import (
    CustomerProfile,
    SmallBusinessOwnerProfile,
    SubcontractorProfile,
)
from user_accounts.serializers.users import UserMeSerializer


class MeViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        # GET /me/
        return Response(UserMeSerializer(request.user).data)

    @action(detail=False, methods=["post"], url_path="upgrade/sbo")
    def upgrade_sbo(self, request):
        user = request.user
        user.role = "SBO"
        user.save(update_fields=["role"])

        # ensure base profiles
        try:
            CustomerProfile.objects.get_or_create(user=user)
        except Exception:
            pass
        try:
            SmallBusinessOwnerProfile.objects.get_or_create(user=user)
        except Exception:
            pass

        return Response(
            {"detail": "Upgraded to SBO", "user": UserMeSerializer(user).data},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="upgrade/pm")
    def upgrade_pm(self, request):
        """
        Property Manager is typically a flag/profile in your system.
        If you later want PM as its own profile model, swap it in here.
        For now: set role = 'PM' (simple and works).
        """
        user = request.user
        user.role = "PM"
        user.save(update_fields=["role"])

        try:
            CustomerProfile.objects.get_or_create(user=user)
        except Exception:
            pass

        return Response(
            {"detail": "Upgraded to Property Manager", "user": UserMeSerializer(user).data},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="upgrade/sub")
    def upgrade_sub(self, request):
        user = request.user
        user.role = "SUB"
        user.save(update_fields=["role"])

        try:
            CustomerProfile.objects.get_or_create(user=user)
        except Exception:
            pass
        try:
            SubcontractorProfile.objects.get_or_create(user=user)
        except Exception:
            pass

        return Response(
            {"detail": "Upgraded to Subcontractor", "user": UserMeSerializer(user).data},
            status=status.HTTP_200_OK,
        )
