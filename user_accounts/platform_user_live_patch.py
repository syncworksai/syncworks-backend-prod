from __future__ import annotations

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from user_accounts.models.user_classification import PlatformUserClassification
from user_accounts.serializers.platform_console import PlatformUserSerializer
from user_accounts.viewsets.platform_console import PlatformUsersViewSet


ALLOWED_KINDS = {choice for choice, _ in PlatformUserClassification.Kind.choices}
INTELLIGENCE_LIST_FIELDS = {"roles", "modules", "subscriptions"}
INTELLIGENCE_TEXT_FIELDS = {"acquisition_source", "acquisition_detail"}
INTELLIGENCE_INTEGER_FIELDS = {
    "customers_brought",
    "customers_supplied_by_syncworks",
    "attributed_revenue_cents",
    "paid_cents",
    "payable_cents",
}


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


def _validated_intelligence(request_data, current):
    incoming = request_data.get("intelligence")
    if incoming is None:
        return current
    if not isinstance(incoming, dict):
        raise ValueError("intelligence must be an object.")

    result = dict(current or {})
    for key in INTELLIGENCE_LIST_FIELDS:
        if key in incoming:
            value = incoming.get(key)
            if not isinstance(value, list):
                raise ValueError(f"{key} must be a list.")
            result[key] = sorted({str(item).strip().upper() for item in value if str(item).strip()})

    for key in INTELLIGENCE_TEXT_FIELDS:
        if key in incoming:
            result[key] = str(incoming.get(key) or "").strip()[:240]

    for key in INTELLIGENCE_INTEGER_FIELDS:
        if key in incoming:
            try:
                value = int(incoming.get(key) or 0)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a whole number.")
            result[key] = max(0, value)

    return result


def classify_user(viewset, request, pk=None):
    user = viewset.get_object()
    requested_kind = request.data.get("classification", request.data.get("kind"))
    item, _ = PlatformUserClassification.objects.get_or_create(user=user)

    if requested_kind is not None:
        kind = str(requested_kind or "").strip().upper()
        if kind not in ALLOWED_KINDS:
            return Response(
                {"detail": "Invalid classification.", "allowed": sorted(ALLOWED_KINDS)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        item.kind = kind

    if "note" in request.data:
        item.note = str(request.data.get("note") or "").strip()

    try:
        item.intelligence = _validated_intelligence(request.data, item.intelligence)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

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
