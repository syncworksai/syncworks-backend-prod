from __future__ import annotations

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from user_accounts.models import Notification, PlatformNewsItem
from user_accounts.serializers.notifications import PlatformNewsItemSerializer

User = get_user_model()


class IsGodMode(BasePermission):
    def has_permission(self, request, view):
        u = request.user
        return bool(
            u
            and u.is_authenticated
            and (getattr(u, "is_platform_admin", False) or getattr(u, "is_superuser", False))
        )


class PlatformBroadcastAPIView(APIView):
    """
    POST /api/v1/platform/broadcasts/
    Body:
      {
        "title": "Maintenance Tonight",
        "body": "We are shipping tickets at 10pm.",
        "send_to": "ALL" | "CUSTOMERS" | "SBO" | "PM"   (optional, default ALL)
      }
    Creates Notification(type=BROADCAST) for recipients.
    """
    permission_classes = [IsAuthenticated, IsGodMode]

    def post(self, request):
        title = (request.data.get("title") or "").strip()
        body = (request.data.get("body") or "").strip()
        send_to = (request.data.get("send_to") or "ALL").strip().upper()

        if not title or not body:
            return Response({"detail": "title and body are required."}, status=status.HTTP_400_BAD_REQUEST)

        qs = User.objects.all()

        # If your User.role exists; else broadcasts to all
        if send_to != "ALL":
            qs = qs.filter(role=send_to)

        recipients = list(qs.values_list("id", flat=True))

        notifications = [
            Notification(
                recipient_id=uid,
                actor=request.user,
                type=Notification.TYPE_BROADCAST,
                title=title,
                body=body,
                data={"send_to": send_to},
            )
            for uid in recipients
        ]

        Notification.objects.bulk_create(notifications, batch_size=500)

        return Response(
            {"detail": "Broadcast sent.", "recipients": len(recipients)},
            status=status.HTTP_201_CREATED,
        )


class PlatformNewsReelAdminViewSet(ModelViewSet):
    """
    God Mode CRUD for the news reel.
    /api/v1/platform/news-reel/
    Supports multipart file upload: image=<file>
    """
    serializer_class = PlatformNewsItemSerializer
    permission_classes = [IsAuthenticated, IsGodMode]
    queryset = PlatformNewsItem.objects.all().order_by("-created_at")

    # ✅ This is what makes file upload work
    parser_classes = [MultiPartParser, FormParser, JSONParser]
