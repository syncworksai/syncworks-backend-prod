from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from user_accounts.models.user_classification import PlatformUserClassification
from user_accounts.serializers.platform_console import PlatformUserSerializer
from user_accounts.viewsets.platform_console import PlatformUsersViewSet


ALLOWED_KINDS = {choice for choice, _ in PlatformUserClassification.Kind.choices}


def live_queryset(viewset):
    qs = viewset.queryset if getattr(viewset, "queryset", None) is not None else None
    if qs is None:
        from django.contrib.auth import get_user_model
        qs = get_user_model().objects.all()
    qs = qs.select_related("platform_classification").order_by("-date_joined")
    q = str(viewset.request.query_params.get("q") or "").strip()
    kind = str(viewset.request.query_params.get("classification") or "").strip().upper()
    if q:
        qs = qs.filter(
            Q(email__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(username__icontains=q)
        )
    if kind:
        if kind == PlatformUserClassification.Kind.UNCLASSIFIED:
            qs = qs.filter(platform_classification__isnull=True)
        elif kind in ALLOWED_KINDS:
            qs = qs.filter(platform_classification__kind=kind)
    return qs


def classify_user(viewset, request, pk=None):
    user = viewset.get_object()
    kind = str(request.data.get("classification") or request.data.get("kind") or "").strip().upper()
    note = str(request.data.get("note") or "").strip()
    if kind not in ALLOWED_KINDS:
        return Response(
            {"detail": "Invalid classification.", "allowed": sorted(ALLOWED_KINDS)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    item, _ = PlatformUserClassification.objects.get_or_create(user=user)
    item.kind = kind
    item.note = note
    item.classified_by = request.user
    item.classified_at = timezone.now()
    item.save()
    return Response(PlatformUserSerializer(user, context={"request": request}).data)


def update_user(viewset, request, pk=None):
    return classify_user(viewset, request, pk)


PlatformUsersViewSet.get_queryset = live_queryset
PlatformUsersViewSet.update = update_user
PlatformUsersViewSet.partial_update = update_user
PlatformUsersViewSet.classify = classify_user
